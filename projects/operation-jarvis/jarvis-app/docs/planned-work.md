# Pending work and status reconciliation

[App overview](../README.md) · [Documentation index](README.md) · [Operations](operations.md)

This is a reconciliation register, not a promise to implement or deploy features. The previous documentation contains overlapping "installed", "candidate", and "not deployed" claims. No live host, signed archive, or physical-device audit was performed during this documentation reorganization.

## Status vocabulary

- **Implemented:** behavior exists in checked-in source. This alone does not show that tests pass or the feature is enabled.
- **Verified:** a named verification run passed against an exact source/artifact. A historical run does not verify a later edit.
- **Deployed:** an exact audited artifact or host revision was installed, supported by owner-controlled evidence.
- **Accepted:** the relevant physical behavior was checked on approved devices.
- **Proposed or unresolved:** a plan or conflicting status that needs reconciliation before being represented as shipped.

## Items requiring reconciliation

| Item | Preserved evidence | What remains to establish |
|---|---|---|
| Layered activity animation | [Candidate notes](development-history.md#layered-activity-animation-candidate-not-deployed) explicitly say not deployed and distinguish implementation from energy/motion acceptance. | Exact source/artifact, whether it was later installed, and physical acceptance. |
| Siri unused-New-slot admission | [Candidate notes](development-history.md#siri-unused-new-slot-candidate-not-deployed) describe coordinated app/terminald/extension rollout; later prose describes the behavior as working. | Compatible live host/client revisions and explicit admission, refusal, and navigation acceptance. |
| Session layout and lifecycle | [Nine-session candidate](development-history.md#nine-session-candidate-build-153) and [Build 155 status notes](development-history.md#new-session-status-build-155) supersede older six-slot plans. | Actual live sessions and loaded extensions, without creating, restarting, or replacing any session during a documentation check. |
| Installed native build | The archive opens with Build 160 claims but also retains Build 147, Build 126, and source Build 127 status text. | Exact current installed products and private acceptance evidence. No single historical heading resolves this. |
| Notifications | [APNs plan and later addenda](implementation-history.md#native-iphone-and-apple-watch-apns-scheduled-job-notifications) document evolving privacy and routing contracts. | Current signed capabilities, owner permissions, registration, dispatch gates, and accepted behavior. Code presence does not imply activation. |

Some of these items may already have been deployed. They are unresolved **in the documentation review**, not asserted to be unfinished engineering work.

## Portfolio media awaiting approval

A real, sanitized iPhone/Watch screenshot pair and a short demonstration would help the public overview. No media was captured, fabricated, or published as part of this change.

Before adding media:

1. Choose an approved build and harmless demonstration content.
2. Capture only the relevant app surfaces, without issuing unapproved device commands or modifying live conversations.
3. Remove or obscure contact data, job results, prompts, credentials, network/device identifiers, and notification content. Check the exported files and metadata, not only the visible crop.
4. Obtain owner approval of the exact public assets.
5. Add descriptive alt text and identify the demonstrated build; label staged/sample content honestly.

Do not use an architecture diagram as if it were a screenshot or imply that an interactive diagram is a live public demo.
