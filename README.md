# ptvc — Pro Tools Version Control

A CLI tool that creates versioned snapshots of Pro Tools sessions via the PTSL gRPC API. Each snapshot copies the `.ptx` session file into a `Versions/` folder with a human-readable markdown log.

Requires Pro Tools 2025+ running on the same machine.

## Install

```bash
brew install craigeley/tap/ptvc
```

Note: The first install takes ~4 minutes because the gRPC dependency compiles from source.

### Development install

If you want to make changes to the code:

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

## Usage

Open a session in Pro Tools, then from any directory:

```bash
ptvc snapshot "Added background vocals"   # create a versioned snapshot
ptvc log                                   # view version history
ptvc info                                  # show session info and version status
ptvc config                                # view current versioning settings
```

## Configuration

```bash
ptvc config --prefix "mix "                # change version prefix (default: " v")
ptvc config --start-number 100             # start numbering at 100
ptvc config --increment-by 0.05            # use decimal increments
ptvc config --zero-pad 4                   # pad to 4 digits (e.g., v0001)
ptvc config --date-format "%Y.%-m"         # switch to date-based versioning
ptvc config --date-format ""               # switch back to numeric
ptvc config --folder-name "Snapshots"      # rename the versions folder
```

Config is stored per-session in the versions folder.