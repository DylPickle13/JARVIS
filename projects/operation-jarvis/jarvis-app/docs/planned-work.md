# Build and deployment notes to check

[App overview](../README.md) · [Documentation index](README.md) · [Operations](operations.md)

Some older notes disagree about which builds and features were installed. This page collects those questions so they can be checked against the actual setup. The documentation review did not inspect live hosts, signed archives, or physical devices.

## Status vocabulary

These terms describe different steps, not interchangeable claims:

- **Implemented:** the behavior is in source, but may not be tested or enabled.
- **Verified:** a recorded test run passed for a specific revision or build, not later edits.
- **Deployed:** the audited build or host revision was installed, with a private owner record.
- **Accepted:** the behavior was checked on the approved physical devices.
- **Proposed or unresolved:** a plan, or a status that still needs checking.

## Items requiring reconciliation

| Item | Preserved evidence | What remains to establish |
|---|---|---|
| Layered activity animation | [Candidate notes](development-history.md#layered-activity-animation-candidate-not-deployed) explicitly say not deployed and distinguish implementation from energy/motion acceptance. | Exact source/artifact, whether it was later installed, and physical acceptance. |
| Siri unused-New-slot admission | [Candidate notes](development-history.md#siri-unused-new-slot-candidate-not-deployed) describe coordinated app/terminald/extension rollout; later prose describes the behavior as working. | Compatible live host/client revisions and explicit admission, refusal, and navigation acceptance. |
| Session layout and lifecycle | [Nine-session candidate](development-history.md#nine-session-candidate-build-153) and [Build 155 status notes](development-history.md#new-session-status-build-155) supersede older six-slot plans. | Actual live sessions and loaded extensions, without creating, restarting, or replacing any session during a documentation check. |
| Installed native build | The archive opens with Build 160 claims but also retains Build 147, Build 126, and source Build 127 status text. | Exact current installed products and private acceptance evidence. No single historical heading resolves this. |
| Notifications | [APNs plan and later addenda](implementation-history.md#native-iphone-and-apple-watch-apns-scheduled-job-notifications) document evolving privacy and routing contracts. | Current signed capabilities, owner permissions, registration, dispatch gates, and accepted behavior. Code presence does not imply activation. |

Some items may already be installed and working. An open question here means the documentation is unclear, not necessarily that the feature is unfinished.

## Portfolio media and future captures

The approved [simulator showcase](../../../../docs/media/README.md) includes four screenshots, an overview image, and an eight-second UI animation video. It uses isolated simulator builds and read-only sample data, labeled in each export. No live integrations or physical devices were used.

Before adding or replacing media:

1. Choose an approved build and harmless demonstration content.
2. Capture only the relevant app surfaces, without issuing unapproved device commands or modifying live conversations.
3. Remove or obscure contact data, job results, prompts, credentials, network/device identifiers, and notification content. Check the exported files and metadata, not only the visible crop.
4. Obtain owner approval of the exact public assets.
5. Add descriptive alt text, identify the build, and label any sample data.

Keep diagrams, simulator captures, and live demos clearly distinguished.
