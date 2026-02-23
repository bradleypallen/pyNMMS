# CLI Usage

## Overview

pyNMMS provides the `pynmms` command with three subcommands:

```bash
pynmms tell   # Add atoms or consequences to a base
pynmms ask    # Query derivability
pynmms repl   # Interactive REPL
```

## Notation

**Notational conventions.**

- *A*, *B*, ... range over sentences of the object language.
- *p*, *q*, *r*, ... range over atomic sentences.
- &Gamma;, &Delta; range over finite sets of sentences.

**The two turnstiles:**

- &Gamma; `|~` &Delta; &mdash; a **base consequence**. The `tell` command *adds* the pair (&Gamma;, &Delta;) to the base consequence relation |~<sub>B</sub>. In the theory, |~<sub>B</sub> is a given relation (Definition 1, Ch. 3); in the tool it is built incrementally.
- &Gamma; `=>` &Delta; &mdash; a **sequent**. The `ask` command tests whether the sequent &Gamma; &rArr; &Delta; is *derivable*, i.e., whether there exists a proof tree whose leaves are all axioms of the base.

Note: `|~` is input (asserting into the base); `=>` is query (testing derivability from the base). Both &Gamma; and &Delta; may be empty.

## Propositional Object Language

The propositional object language is defined by the following unambiguous grammar:

```
sentence   ::=  impl
impl       ::=  disj ( '->' disj )*            (* right-associative *)
disj       ::=  conj ( '|' conj )*             (* left-associative *)
conj       ::=  unary ( '&' unary )*           (* left-associative *)
unary      ::=  '~' unary | atom | '(' sentence ')'
atom       ::=  IDENTIFIER
```

Where `IDENTIFIER` is any non-empty string of letters, digits, and underscores beginning with a letter or underscore. Precedence (tightest to loosest): `~`, `&`, `|`, `->`.

**Connective glossary:**

| Symbol | Name | Arity |
|--------|------|-------|
| `~` | negation | prefix unary |
| `&` | conjunction | binary, left-associative |
| &#124; | disjunction | binary, left-associative |
| `->` | conditional (implication) | binary, right-associative |

## The NMMS_RQ Object Language

The `--rq` flag enables **NMMS_RQ**, an extension of the propositional NMMS object language with ALC-style restricted quantifiers.

**Atoms.** In propositional NMMS, atoms are bare identifiers. In NMMS_RQ, atoms are **ground atomic formulas**:

| Form | Name | Example |
|------|------|---------|
| *C*(*a*) | concept assertion | `Happy(alice)` |
| *R*(*a*, *b*) | role assertion | `hasChild(alice,bob)` |

Bare propositional letters are not valid in NMMS_RQ.

**Grammar.** The NMMS_RQ grammar replaces the propositional `atom` production:

```
atom       ::=  CONCEPT '(' INDIVIDUAL ')'                  (* concept assertion *)
             |  ROLE '(' INDIVIDUAL ',' INDIVIDUAL ')'      (* role assertion *)
sentence   ::=  ...                                          (* all propositional forms *)
             |  'ALL' ROLE '.' CONCEPT '(' INDIVIDUAL ')'   (* universal restriction *)
             |  'SOME' ROLE '.' CONCEPT '(' INDIVIDUAL ')'  (* existential restriction *)
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

# Add atoms with annotations
pynmms tell -b base.json 'atom p "Tara is human"'

# Empty consequent (incompatibility)
pynmms tell -b base.json "s, t |~"

# Empty antecedent (unconditional assertion)
pynmms tell -b base.json "|~ p"
```

### Syntax

- **Consequence**: `A |~ B` or `A, B |~ C, D` (comma-separated)
- **Incompatibility**: `A, B |~` (empty consequent)
- **Unconditional assertion**: `|~ A` (empty antecedent)
- **Atom**: `atom X`
- **Atom with annotation**: `atom X "description"`

### Options

| Flag | Description |
|------|-------------|
| `-b`, `--base` | Path to JSON base file (required) |
| `--create` | Create the base file if missing |
| `--rq` | Use restricted quantifier mode |
| `--json` | Output as JSON (pipe-friendly) |
| `-q`, `--quiet` | Suppress output; rely on exit code |
| `--batch FILE` | Read statements from FILE (use `-` for stdin) |

## `pynmms ask`

Query whether a sequent is derivable.

```bash
pynmms ask -b base.json "A => B"
# Output: DERIVABLE

pynmms ask -b base.json "A => C"
# Output: NOT DERIVABLE
```

### Exit codes

Following the `grep`/`diff`/`cmp` convention:

| Exit code | Meaning |
|-----------|---------|
| 0 | Derivable |
| 1 | Error |
| 2 | Not derivable |

### Options

| Flag | Description |
|------|-------------|
| `-b`, `--base` | Path to JSON base file (required) |
| `--trace` | Print the proof trace |
| `--max-depth N` | Set the maximum proof depth (default: 25) |
| `--rq` | Use restricted quantifier mode |
| `--json` | Output as JSON (pipe-friendly) |
| `-q`, `--quiet` | Suppress output; rely on exit code |
| `--batch FILE` | Read sequents from FILE (use `-` for stdin) |

### JSON output

```bash
pynmms ask -b base.json --json "A => B"
# Output: {"status":"DERIVABLE","sequent":{"antecedent":["A"],"consequent":["B"]},"depth_reached":0,"cache_hits":0}
```

With `--trace`, adds a `"trace"` array.

### Stdin input

```bash
echo "A => B" | pynmms ask -b base.json -
```

### Batch mode

```bash
pynmms ask -b base.json --batch queries.txt
pynmms ask -b base.json --json --batch queries.txt
cat queries.txt | pynmms ask -b base.json --batch -
```

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
| tell A &#124;~ B | Add a consequence |
| tell A, B &#124;~ | Add incompatibility (empty consequent) |
| tell &#124;~ A | Add unconditional assertion (empty antecedent) |
| tell atom A | Add an atom |
| tell atom A "desc" | Add an atom with annotation |
| ask A => B | Query derivability |
| show | Display the current base (with annotations) |
| trace on/off | Toggle proof trace display |
| save &lt;file&gt; | Save base to JSON |
| load &lt;file&gt; | Load base from JSON |
| help | Show available commands |
| quit | Exit the REPL |

### Example Session

```
$ pynmms repl
Starting with empty base.
pyNMMS REPL. Type 'help' for commands.

pynmms> tell atom p "Tara is human"
Added atom: p — Tara is human
pynmms> tell atom q "Tara's body temp is 37°C"
Added atom: q — Tara's body temp is 37°C
pynmms> tell p |~ q
Added: {'p'} |~ {'q'}
pynmms> tell s, t |~
Added: set() |~ set()
pynmms> ask p => q
DERIVABLE
pynmms> ask p, r => q
NOT DERIVABLE
pynmms> show
Language (4 atoms):
  p — Tara is human
  q — Tara's body temp is 37°C
  s
  t
Consequences (2):
  {'p'} |~ {'q'}
  {'s', 't'} |~ set()
pynmms> save mybase.json
Saved to mybase.json
pynmms> quit
```

## Batch files

### Tell batch format

One statement per line. Blank lines and `#` comments are skipped:

```
# mybase.base
atom p "Tara is human"
atom q "Tara's body temp is 37°C"
p |~ q
s, t |~
```

```bash
pynmms tell -b base.json --create --batch mybase.base
```

### RQ batch format

With `--rq`, batch files also support `schema` lines (with optional quoted annotations):

```
atom Happy(alice) "Alice is happy"
atom hasChild(alice,bob)
Happy(alice) |~ Good(alice)
schema concept hasChild alice Happy "All children of alice are happy"
schema inference hasChild alice Serious HeartAttack "Serious children risk heart attacks"
```

```bash
pynmms tell -b rq_base.json --create --rq --batch rq_base.base
```

### Ask batch format

One sequent per line:

```
# queries.txt
A => B
A, B => C
=> A -> B
```

```bash
pynmms ask -b base.json --batch queries.txt
pynmms ask -b base.json --json --batch queries.txt  # JSONL output
```
