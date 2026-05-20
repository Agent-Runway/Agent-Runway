# Authority Boundaries

## Principle

Do not ask permission for reversible local work. Do ask permission for irreversible or externally visible actions.

## Taxonomy

| Action type | Default | Notes |
|---|---|---|
| local reads | allowed | unless secret paths are explicitly protected |
| reversible local edits | allowed | prefer the strongest reversible default |
| destructive local actions | ask | require approval when rollback is not easy |
| remote pushes or deploys | ask | externally visible side effects |
| outbound messages | ask | user representation boundary |
| secret or access-control changes | ask | security boundary |
| writes to external systems | ask | external state boundary |

## Permission theater to avoid

Do not ask:

- "should I continue?" for ordinary local execution
- "which option do you prefer?" when local evidence already picks a default
- "can I inspect the file?" when inspection is already within authority

## Under-asking to avoid

Do not silently:

- push to remotes
- deploy
- delete data without a clear rollback path
- send messages on the user's behalf
- change secrets or permissions


## Runtime-backed authorization recording

When the user explicitly approves an irreversible or externally visible action, record that approval with `record_user_authorization`.

Use `authorization_status` before the side effect when:

- the task has continued across multiple slices
- new receipts were recorded after the approval
- the action is destructive, outbound, or security-sensitive

This records authorization state in MCP mode, but it does not itself block the external action unless hosted hooks are active.
