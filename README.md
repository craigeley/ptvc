# ptvc — Pro Tools Version Control

`ptvc` is a CLI tool that creates versioned snapshots of Pro Tools sessions via the PTSL gRPC API. Each snapshot copies the `.ptx` session file into a `Versions/` folder alongside the session, with a human-readable markdown log.

Requires Pro Tools 2025+ running on the same machine.

## Install

```bash
brew install craigeley/tap/ptvc
```

## How It Works

By default, Pro Tools makes automatic backups of session files every x minutes based on user settings. However, these backups have hardcoded numbers, are eventually deleted over time, and do not contain any readable notes or metadata.

`ptvc` creates manual backups with user-specified version numbers and an accompanying notes file to help you manage your backups and generate text files that could be easily used in `git`-based workflows. It was built for podcast and audio documentary professionals, but could be useful for anyone using Pro Tools.

When you run `ptvc snapshot`, it:

1. Connects to Pro Tools via its built-in gRPC server (`localhost:31416`)
2. Saves the current session
3. Copies the `.ptx` file into a `Versions/` folder within the session folder
4. Updates a machine-readable JSON index and a human-readable markdown log

You can run `ptvc` from any directory in your terminal — it asks Pro Tools which session is open and works from there.

## Usage

### Creating snapshots

Basic usage: `ptvc snapshot "note here"`; note that `s` can be used as a shortcut for `snapshot.

```bash
ptvc snapshot "Added theme music"
ptvc s "Added theme music"                 # shorthand alias
ptvc snapshot                              # no notes
ptvc snapshot "Rough cut" --tag "rough"    # custom one-off label
ptvc snapshot "Final mix" --bump 1.00      # jump to version 1.00
```

The `--tag` flag overrides the version label for a single snapshot without affecting the numbering sequence. The `--bump` flag jumps to a specific version number, and future snapshots increment from there.

### Viewing history

```bash
ptvc log     # display the version history
ptvc info    # show session info, version count, and next version number
```

### Configuration

Settings are stored per-session in the `Versions/` folder. Run `ptvc config` with no flags to view current settings and a preview of the next few version numbers.

#### Version numbering

```bash
ptvc config --prefix " v"            # prefix before the number (default: " v")
ptvc config --start-number 1         # starting number (default: 1)
ptvc config --increment-by 1         # increment per snapshot (default: 1)
ptvc config --zero-pad 3             # zero-pad digits (default: 3, e.g., v001)
```

Examples of what different configs produce:

| Config | Sequence |
|--------|----------|
| Default | `My Session v001.ptx`, `My Session v002.ptx`, ... |
| `--prefix " mix" --zero-pad 0` | `My Session mix1.ptx`, `My Session mix2.ptx`, ... |
| `--start-number 0.00 --increment-by 0.05` | `My Session v0.00.ptx`, `My Session v0.05.ptx`, ... |

#### Date-based versioning

Instead of sequential numbers, you can use date-based version strings with any Python [strftime](https://strftime.org/) format:

```bash
ptvc config --date-format "%Y.%-m"         # v2026.3, v2026.3-2, v2026.4, ...
ptvc config --date-format "%Y.%-m.%-d"     # v2026.3.17, v2026.3.17-2, ...
ptvc config --date-format ""               # switch back to numeric
```

If multiple snapshots land on the same date string, a counter is appended automatically (`-2`, `-3`, etc.).

#### Versions folder

```bash
ptvc config --folder-name "Snapshots"      # rename the versions folder
```

#### Session info text export

Optionally export Pro Tools' session info (file list, markers, plugin list) as a text file alongside each snapshot. This could be useful for diffing in git.

```bash
ptvc config --text-export on               # enable (off by default)
ptvc config --text-export off              # disable
ptvc config --text-format UTF8             # format: UTF8 (default), TextEdit, or Excel
```

The text file is saved in the session's top-level folder and overwrites on each snapshot, so it always reflects the latest state.

You can also skip the export for a single snapshot:

```bash
ptvc snapshot "Quick save" --no-text-export
```

#### Saving to the session root

By default, snapshots are saved into the `Versions/` folder. Use `--root` to save the snapshot alongside the main session file instead:

```bash
ptvc snapshot "Alt mix for client" --root
```

## Development

```bash
brew install pipx
git clone https://github.com/craigeley/ptvc.git
pipx install -e ./ptvc
```

You may need Homebrew Python and `~/.local/bin` on your PATH. Add to `~/.zshrc`:

```bash
export PATH="$(brew --prefix)/opt/python@3/libexec/bin:$PATH"
export PATH="$HOME/.local/bin:$PATH"
```
