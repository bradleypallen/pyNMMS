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
atom       ::=  IDENTIFIER ( '(' IDENTIFIER ( ',' IDENTIFIER )* ')' )?
             |  '<' QUOTED '>'
```

Where `IDENTIFIER` is any non-empty string of letters, digits, and underscores beginning with a letter or underscore, and `QUOTED` is any run of characters other than `<` and `>`. Precedence (tightest to loosest): `~`, `&`, `|`, `->`.

An atom is therefore one of three things:

| Form | Example | Notes |
|------|---------|-------|
| identifier | `p`, `Tara_is_human` | the propositional case |
| applied identifier | `Man(socrates)`, `hasChild(alice,bob)` | the NMMS_Onto forms; also accepted in propositional mode by the parser, though `MaterialBase` rejects them outside `--onto` |
| quoted atom | `<ex:tweety a ex:Bird>` | content taken verbatim, brackets included in the atom's name; use for IRIs or any token that would otherwise be misread as a connective |

Anything else in atom position is a parse error. In particular, a connective written as a word is rejected with a hint rather than silently accepted as an atom:

```
$ pynmms ask -b base.json "(p conj q) => r"
Error: Malformed sentence: 'p conj q' is not a valid atom. ... Did you mean a connective? Use ~ (not), & (and), | (or), -> (implies).
```

Commas inside applied atoms and quoted atoms do not split a sequent, so `hasChild(alice,bob), <x, y> => Person(bob)` has a two-element antecedent. Whitespace inside an applied atom is not significant: `hasChild(alice, bob)` and `hasChild(alice,bob)` name the same atom.

## Robustness of Base Entries

Every base consequence and every ontology schema carries a **robustness policy** that says how far it survives additions to its antecedent and consequent (its range of subjunctive robustness, Hlobil & Brandom 2025, Ch. 5, restricted to singleton additions):

| Policy | `tell` syntax | Matches |
|--------|---------------|---------|
| exact (default) | `A, B \|~ C` | only `A, B ⇒ C` itself; any further premise or conclusion defeats it |
| guarded | `A, B \|~ C unless X, Y` | any `Γ ⊇ {A, B}`, `Δ ⊇ {C}` unless `X` or `Y` is in Γ |
| monotone | `A, B \|~ C monotone` | any `Γ ⊇ {A, B}`, `Δ ⊇ {C}` |

```
$ pynmms tell -b birds.json --create "Bird |~ Flies unless Penguin, Dead"
Added consequence: {'Bird'} |~ {'Flies'} [unless Dead, Penguin]
$ pynmms ask -b birds.json "Bird, Tall => Flies"      # exit 0: irrelevant premise is harmless
$ pynmms ask -b birds.json "Bird, Penguin => Flies"   # exit 2: relevant defeat
```

The same clause applies to schema lines in `--onto` mode; there the defeaters are **concept names**, instantiated on the individuals of the matched consequent:

```
schema subClassOf Bird Flies unless Penguin "birds fly"
schema disjointWith Alive Dead monotone
```

With the guarded schema, `Bird(a), Tall(a) => Flies(a)` is derivable and `Bird(a), Penguin(a) => Flies(a)` is not. With the monotone disjointness, `Alive(a), Dead(a), Tall(a) =>` is derivable, and by the II condition so is `Alive(a), Tall(a) => ~Dead(a)`.

Base files record the policy on every entry as a `robustness` object; files written before v0.7 have no such field and load as exact.

**Connective glossary:**

| Symbol | Name | Arity |
|--------|------|-------|
| `~` | negation | prefix unary |
| `&` | conjunction | binary, left-associative |
| &#124; | disjunction | binary, left-associative |
| `->` | conditional (implication) | binary, right-associative |

## The NMMS_Onto Object Language

The `--onto` flag enables **NMMS_Onto**, an ontology engineering extension of the propositional NMMS object language with concept and role assertions. The vocabulary is borrowed from W3C RDFS and OWL for familiarity; the semantics are those of NMMS (exact-match defeasibility, no weakening, no transitivity).

**Atoms.** In propositional NMMS, atoms are bare identifiers. In NMMS_Onto, atoms are **ground atomic formulas**:

| Form | Name | Example |
|------|------|---------|
| *C*(*a*) | concept assertion | `Happy(alice)` |
| *R*(*a*, *b*) | role assertion | `hasChild(alice,bob)` |

Bare propositional letters are not valid in NMMS_Onto.

**Grammar.** The NMMS_Onto grammar replaces the propositional `atom` production:

```
atom       ::=  CONCEPT '(' INDIVIDUAL ')'                  (* concept assertion *)
             |  ROLE '(' INDIVIDUAL ',' INDIVIDUAL ')'      (* role assertion *)
sentence   ::=  ...                                          (* all propositional forms *)
```

**Ontology Schemas.** In ontology mode, the `tell` command also supports schema registration. Schemas are macros that generate families of ordinary base axioms:

| Schema | CLI syntax | Generated axiom pattern |
|--------|-----------|------------------------|
| `subClassOf` | `schema subClassOf C D` | {C(x)} \|~ {D(x)} for any x |
| `range` | `schema range R C` | {R(x,y)} \|~ {C(y)} for any x,y |
| `domain` | `schema domain R C` | {R(x,y)} \|~ {C(x)} for any x,y |
| `subPropertyOf` | `schema subPropertyOf R S` | {R(x,y)} \|~ {S(x,y)} for any x,y |
| `disjointWith` | `schema disjointWith C D` | {C(x), D(x)} \|~ {} for any x |
| `disjointProperties` | `schema disjointProperties R S` | {R(x,y), S(x,y)} \|~ {} for any x,y |
| `jointCommitment` | `schema jointCommitment C1,C2 D` | {C1(x), C2(x)} \|~ {D(x)} for any x |

Each schema line may end with `unless C1, C2` (guarded) or `monotone`; see [Robustness of Base Entries](#robustness-of-base-entries).

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
| `--onto` | Use ontology mode (concept/role assertions with schema-level macros) |
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
| `--onto` | Use ontology mode (concept/role assertions with schema-level macros) |
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
Added atom: p -- Tara is human
pynmms> tell atom q "Tara's body temp is 37C"
Added atom: q -- Tara's body temp is 37C
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
  p -- Tara is human
  q -- Tara's body temp is 37C
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
atom q "Tara's body temp is 37C"
p |~ q
s, t |~
```

```bash
pynmms tell -b base.json --create --batch mybase.base
```

### Ontology batch format

With `--onto`, batch files also support `schema` lines (with optional quoted annotations):

```
atom Man(socrates) "Socrates is a man"
atom hasChild(alice,bob)
Man(socrates) |~ Mortal(socrates)
schema subClassOf Man Mortal "All men are mortal"
schema range hasChild Person "Children are persons"
schema domain hasChild Parent "Parents have children"
schema subPropertyOf hasChild hasDescendant "Children are descendants"
schema disjointWith Alive Dead "Life and death are incompatible"
schema disjointProperties employs isEmployedBy "Cannot both employ and be employed by"
```

```bash
pynmms tell -b onto_base.json --create --onto --batch onto_base.base
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
