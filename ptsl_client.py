"""
Lightweight Python gRPC client for Pro Tools Scripting Library (PTSL).

Connects to Pro Tools' built-in gRPC server on localhost:31416 and sends
commands using the PTSL protocol.
"""

import json
import grpc

# These are generated from PTSL.proto — see generate_proto.sh
import PTSL_pb2
import PTSL_pb2_grpc

# Must match the SDK version that your Pro Tools version expects
PTSL_VERSION_MAJOR = 2025
PTSL_VERSION_MINOR = 10
PTSL_VERSION_REVISION = 0

DEFAULT_ADDRESS = "localhost:31416"


class PTSLClient:
    """Client for communicating with Pro Tools via PTSL gRPC."""

    def __init__(self, address=DEFAULT_ADDRESS):
        self.address = address
        self.session_id = ""
        options = [("grpc.max_receive_message_length", 2**31 - 1)]
        self.channel = grpc.insecure_channel(address, options=options)
        self.stub = PTSL_pb2_grpc.PTSLStub(self.channel)

    def close(self):
        self.channel.close()

    def send_command(self, command_id, body_json=""):
        """Send a PTSL command and return the parsed response."""
        header = PTSL_pb2.RequestHeader(
            task_id="",
            command=command_id,
            version=PTSL_VERSION_MAJOR,
            version_minor=PTSL_VERSION_MINOR,
            version_revision=PTSL_VERSION_REVISION,
            session_id=self.session_id,
        )
        request = PTSL_pb2.Request(
            header=header,
            request_body_json=body_json,
        )
        try:
            response = self.stub.SendGrpcRequest(request)
        except grpc.RpcError as e:
            raise RuntimeError(
                f"gRPC error: {e.code().name} — {e.details()}"
            ) from e

        status = response.header.status
        # TaskStatus from proto: 3 = Completed, 4 = Failed
        if status == 4:
            error_body = response.response_error_json
            response_body = response.response_body_json
            raise RuntimeError(
                f"PTSL command failed.\n"
                f"  Error: {error_body}\n"
                f"  Response: {response_body}"
            )

        return response

    def register_connection(self, company_name, application_name):
        """Register with Pro Tools. Must be called before any other command."""
        body = json.dumps({
            "company_name": company_name,
            "application_name": application_name,
        })
        response = self.send_command(PTSL_pb2.CId_RegisterConnection, body)
        result = json.loads(response.response_body_json)
        self.session_id = result["session_id"]
        return self.session_id

    def get_session_name(self):
        """Get the name of the currently open Pro Tools session."""
        response = self.send_command(PTSL_pb2.CId_GetSessionName)
        return json.loads(response.response_body_json).get("session_name", "")

    def get_session_path(self):
        """Get the file path of the currently open Pro Tools session."""
        response = self.send_command(PTSL_pb2.CId_GetSessionPath)
        result = json.loads(response.response_body_json).get("session_path", "")
        # Response may be a string or a dict with a nested "path" key
        if isinstance(result, dict):
            return result.get("path", "")
        return result

    def save_session(self):
        """Save the current Pro Tools session."""
        self.send_command(PTSL_pb2.CId_SaveSession)

    def save_session_as(self, session_name, session_location):
        """Save the current session as a new file."""
        body = json.dumps({
            "session_name": session_name,
            "session_location": session_location,
        })
        self.send_command(PTSL_pb2.CId_SaveSessionAs, body)

    def get_session_sample_rate(self):
        response = self.send_command(PTSL_pb2.CId_GetSessionSampleRate)
        return json.loads(response.response_body_json).get("sample_rate", "")

    def get_session_bit_depth(self):
        response = self.send_command(PTSL_pb2.CId_GetSessionBitDepth)
        return json.loads(response.response_body_json).get("current_setting", "")

    def get_session_audio_format(self):
        response = self.send_command(PTSL_pb2.CId_GetSessionAudioFormat)
        return json.loads(response.response_body_json).get("current_setting", "")

    def get_track_list(self):
        """Get list of all tracks in the session."""
        body = json.dumps({
            "track_filter_list": [{"filter": "All", "is_inverted": False}],
            "is_filter_list_additive": True,
        })
        response = self.send_command(PTSL_pb2.CId_GetTrackList, body)
        return json.loads(response.response_body_json)

    def get_clip_count(self):
        """Get the total number of clips in the session."""
        body = json.dumps({
            "pagination_request": {"limit": 0, "offset": 0},
        })
        response = self.send_command(PTSL_pb2.CId_GetClipList, body)
        result = json.loads(response.response_body_json)
        # Try pagination total first, fall back to counting the clips array
        pagination = result.get("pagination_response", {})
        total = pagination.get("total", 0)
        if total > 0:
            return total
        return len(result.get("clips", []))

    def export_session_info_as_text(self, output_path):
        """Export session info to a text file."""
        body = json.dumps({
            "include_file_list": True,
            "include_clip_list": True,
            "include_markers": True,
            "include_plugin_list": True,
            "include_track_edls": True,
            "show_sub_frames": False,
            "include_user_timestamps": True,
            "track_list_type": "AllTracks",
            "fade_handling_type": "ShowCrossfades",
            "track_offset_options": "BarsBeats",
            "text_as_file_format": "UTF8",
            "output_type": "ESI_File",
            "output_path": output_path,
        })
        self.send_command(PTSL_pb2.CId_ExportSessionInfoAsText, body)
