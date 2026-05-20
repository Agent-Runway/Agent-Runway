# Receipt Quality

## Principle

A claim should be no stronger than the receipts behind it.

## Evidence ladder

| Strength | Evidence | Typical use |
|---|---|---|
| weak | read-only inspection, prior context, prose reasoning | hypothesis formation |
| medium | direct read-back, diff, local check, one targeted command | slice verification |
| strong | fresh test/build/run output, file hash after write, host-captured tool receipts | completion claims |

## Minimum evidence by claim

| Claim | Minimum evidence |
|---|---|
| file changed as intended | read-back, diff, or file hash after write |
| test passes | fresh command output or Bash receipt with exit code 0 |
| bug fixed | original symptom re-tested and shown absent |
| completion achieved | every completion criterion mapped to receipts |
| blocked on user | evidence that available local work was exhausted first |

## Mapping rule

For `completion_gate`, every criterion must map to one or more receipt ids.

Do not map by narrative similarity. Map by actual evidentiary support.

## Assertion-language danger signs

Downgrade confidence when the summary relies on phrases like:

- should work
- probably fixed
- seems correct
- looks fine
- I think this passes

These phrases usually mean the verification layer is missing.
