# CLI Usage

## Overview

pyNMMS provides the `pynmms` command with three subcommands:

```bash
pynmms tell   # Add atoms or consequences to a base
pynmms ask    # Query derivability
pynmms repl   # Interactive REPL
```

## `pynmms tell`

Add atoms or consequences to a JSON base file.

```bash
# Create a new base and add a consequence
pynmms tell -b base.json --create "A |~ B"

# Add more consequences (base file must exist)
pynmms tell -b base.json "B |~ C"

# Add atoms
pynmms tell -b base.json "atom X"
```

### Syntax

- **Consequence**: `A |~ B` or `A, B |~ C, D` (comma-separated)
- **Atom**: `atom X`

## `pynmms ask`

Query whether a sequent is derivable.

```bash
pynmms ask -b base.json "A => B"
# Output: DERIVABLE

pynmms ask -b base.json "A => C"
# Output: NOT DERIVABLE
```

### Options

- `--trace`: Print the proof trace
- `--max-depth N`: Set the maximum proof depth (default: 25)

```bash
pynmms ask -b base.json --trace "=> A -> B"
# Output:
# DERIVABLE
#
# Proof trace:
#   [R→] on A -> B
#     AXIOM: A => B
#
# Depth reached: 1
# Cache hits: 0
```

## `pynmms repl`

Interactive REPL for exploring reason relations.

```bash
pynmms repl
pynmms repl -b base.json  # Load existing base
```

### REPL Commands

| Command | Description |
|---------|-------------|
| `tell A \|~ B` | Add a consequence |
| `tell atom A` | Add an atom |
| `ask A => B` | Query derivability |
| `show` | Display the current base |
| `trace on/off` | Toggle proof trace display |
| `save <file>` | Save base to JSON |
| `load <file>` | Load base from JSON |
| `help` | Show available commands |
| `quit` | Exit the REPL |

### Example Session

```
$ pynmms repl
Starting with empty base.
pyNMMS REPL. Type 'help' for commands.

pynmms> tell A |~ B
Added: {'A'} |~ {'B'}
pynmms> tell B |~ C
Added: {'B'} |~ {'C'}
pynmms> ask A => B
DERIVABLE
pynmms> ask A => C
NOT DERIVABLE
pynmms> trace on
Trace: ON
pynmms> ask => A -> B
DERIVABLE
  [R→] on A -> B
    AXIOM: A => B
  Depth: 1, Cache hits: 0
pynmms> save mybase.json
Saved to mybase.json
pynmms> quit
```
