# Provider Telegram Source Connection

Provider Edition does not use a shared hosted "signal provider" API secret for Telegram.

## Connect a provider Telegram account

1. Provider signs into the Provider Portal.
2. Choose **Connect Telegram signal source** and select the feed.
3. Generate a short-lived one-time source token.
4. In the Telegram account that will submit provider screenshots/signals, send:

   /connectprovider sgs_...

5. The bot consumes the token using its own server-held registration credential.
6. The backend persists one active Telegram -> provider/feed binding.
7. The raw connection token is never stored and cannot be reused.

A new provider/feed token can explicitly rebind the same Telegram identity. The rebind is audited.

## Signal flow

For a connected source:

Telegram screenshot -> bot -> tenant-bound extraction preview -> provider human confirms/edits -> bot -> tenant-bound signal creation -> feed-specific parser policy -> consented feed subscribers only.

The backend source identity is the internal binding id, not a shared provider secret or raw Telegram id.

## Broadcast recipient ownership and source rebinds (offline guard)

Signal creation returns a persisted provider/feed/source identity. Before
broadcasting subscriber cards, the bot checks that identity against the
original Telegram binding; the separately queried recipient list must carry
matching binding/provider/feed identifiers. An HTTP 200 recipient response
containing an error `detail` is refused even if its scope identifiers match.
If the source was rebound between creation and enumeration, or if any recipient
identifier is malformed, the bot **sends no cards** and tells the provider to
inspect history. This
prevents a prior feed's signal being broadcast to a later feed's subscribers.
Recipient enumeration also refuses a provider or feed paused after signal
creation but before recipient lookup (HTTP 403; no subscriber cards). Pausing
a source **after** the recipient lookup remains a non-atomic delivery window.
This is an offline-tested cross-tenant guard, **not** a guarantee of atomic
revocation during Telegram delivery and not actual Telegram/MT5 acceptance.

## Revocation

The Provider Portal lists active source bindings. Revoking a binding immediately prevents that Telegram identity from:

- previewing screenshots through the tenant provider route;
- creating provider signals;
- fetching subscriber recipients.

It does not delete historical signal/audit evidence.

## Local demo compatibility

The historical `SIGNAL_PROVIDER_TELEGRAM_IDS` / `/provider` shared-provider path remains only as a local-demo compatibility route.

When `REQUIRE_LICENSE=true` (hosted Provider Edition):

- the Telegram bot does not register the legacy `/provider` command;
- configured/local provider ids are not accepted as provider authority;
- screenshot/signal submission requires an active persisted feed-bound source binding;
- a direct call into the legacy handler still fails closed and points the user to `/connectprovider`.

Hosted Provider Edition therefore uses only the tenant source-binding flow for provider Telegram submission.

## Hosted role display and legacy identifiers

Hosted `/start` and `/status` never treat a locally configured legacy
screenshot-provider id as provider authority. Without a persisted source
binding, the bot displays the Provider Portal → one-time feed token →
`/connectprovider TOKEN` path. The historic shared-code `/provider` command
is neither registered in hosted mode nor accepted by its handler. Local-demo
compatibility remains unchanged; these are offline UI/authority-boundary checks,
not a real Telegram or broker acceptance receipt.

A failed `/connectprovider` request produces a generic token-reissue message,
not an arbitrary backend `detail` string. The bot never reflects one-time
token text or server diagnostics from that failure into Telegram.

## Provider-source status receipt boundary (offline verified only)

Hosted screenshot eligibility now requires a well-formed `ACTIVE` / `TELEGRAM`
provider-source status response with nonempty binding, provider and feed
identifiers and names. An HTTP 200 with an array, error detail, revoked binding,
other source type or incomplete fields is **not** authority to submit a
screenshot; an existing confirmable preview is invalidated instead. A stale
local-demo provider ID cannot override this hosted refusal. The backend's
authenticated, tenant-bound lookup is still authoritative, and the bot never
treats an identifier/header alone as authentication. Synthetic offline tests
exercise the malformed, revoked and valid cases without Telegram or broker
traffic. This does not establish external provider or MT5 demo acceptance.

## Screenshot extraction failures

The Telegram bot refuses screenshot photos/documents whose reported size exceeds
**5 MiB** *before downloading them*. After resolving the Telegram File, the bot
checks its separately reported size before allocating download bytes, then counts
the downloaded bytearray *before* copying it into an upload. Missing metadata
at either stage never bypasses the actual-byte check; malformed sizes fail closed.
An oversized/invalid attempt clears the previous pending confirmation/edit token. Telegram File resolution/download failures are contained at the bot boundary:
only the safe exception class is logged, not transport exception text that may
contain a bot-token URL. Failed uploads clear their own confirmation state and
show a generic error; a delayed failure from an older attempt cannot erase a
newer's preview. Offline photo/document tests cover both error stages and
overlapping requests. No external Telegram or broker call is used.
Both backend extraction endpoints also
apply the same 5 MiB limit. These are offline-only resource and stale-preview
boundaries, not Telegram-delivery or broker-demo acceptance.

Each new screenshot attempt invalidates any earlier unconfirmed preview.
An attempt-specific nonce also makes an older async authorisation, Telegram
download or backend extraction result inert when a newer screenshot starts; a
late response cannot replace the newer candidate or restore an old confirm
button. The offline concurrency regressions deliberately overlap photo and
document downloads and extractor responses. They do not establish actual
Telegram delivery or broker-demo acceptance.
Hosted mode rechecks the persisted provider/feed binding immediately before
extraction; if it has been revoked or cannot be verified, extraction stops
without falling back to the local-demo endpoint. Backend error bodies and exception messages are not
forwarded into Telegram or operator logs; users receive generic failure text and
logs retain only HTTP status or exception class. Even a backend HTTP 200 is
untrusted: malformed JSON roots, non-string extracted text, invalid preview fields,
non-finite/oversized values, invalid Unicode and Telegram-length-overflow previews
are rejected before any confirmable per-user state is stored. A corrupted older
pending preview also fails closed on Confirm. Responses remain generic, with no
backend payload echoed into logs or Telegram. Offline mocked-transport checks
exercise these boundaries; they are **not** actual Telegram delivery or MT5
demo-account acceptance evidence.

## Screenshot preview confirmation integrity

Each rendered screenshot preview gets a fresh, short callback identifier; Confirm,
Edit and Cancel buttons carry that identifier. Only the **current** matching
preview can be acted on. Buttons in older Telegram messages, previous fixed
`SIGOK`/`SIGEDIT`/`SIGNO` messages, malformed callbacks, repeated Confirm
actions and lost in-memory preview state fail closed. An old button cannot
confirm or cancel the newer screenshot's text. Confirmable state is consumed
before the backend signal-creation call, so repeated taps cannot reuse it.

The bot still rechecks provider-source permission before each valid callback,
then rechecks the preview identifier **after** that asynchronous lookup, so a
newer screenshot arriving during the lookup cannot be confirmed, edited or
cancelled by the earlier button. Revoked sources clear the matching outstanding
preview rather than forwarding it; a superseded preview is never cleared by
the older request.
Edited signal text is also tied to its original preview identifier:
after an asynchronous provider permission check, stale corrections cannot act
if a newer screenshot, Cancel or competing correction invalidated that preview.
A revoked source clears only its still-current edit state. Offline interleaving
tests verify this in memory, not actual Telegram delivery.

A screenshot's confirmable state also retains its original
`binding_id`/`provider_id`/`feed_id` snapshot. Both Confirm and Edit
compare that exact snapshot with the current ACTIVE provider-source binding,
including after the asynchronous permission check; hosted pre-upgrade previews
without a snapshot are refused. The signal-creation path independently
rechecks the original scope immediately before the create POST, so a provider
rebound from feed A to feed B cannot knowingly submit A's preview using B's
binding. A different current provider/feed refuses the pending preview;
providers must capture a new screenshot. The existing backend reuses a binding
ID on rebind. An A→B→A round-trip or revocation followed by same-feed reconnect
can restore the same three identifiers and escape this client-only comparison;
a connection-generation/transactional backend check remains unimplemented.
Offline interleaving tests cover A-preview → B-rebind
→ Confirm/Edit, rebind between the two pre-create checks, and a matching
unchanged-source positive path. No genuine Telegram traffic was used.

This is a **client-side fail-closed check, not a transaction lock**. A rebind
between the final status read and backend POST may still persist a signal
against the newer feed; the later persisted signal/recipient checks refuse
the mismatched subscriber broadcast, but an unconfirmed provider should
inspect feed history rather than blindly retry. Server-side transactional
binding checks and real Telegram/MT5 demo evidence remain separate work.

The source's backend remains responsible for identity, tenant policy,
subscriber consent and idempotent signal processing. The binding here is
an **in-memory preview integrity guard**, not an authentication credential, a
persistent queue or broker execution acceptance evidence. Restarting the bot
invalidates old preview buttons; providers must send a new screenshot.

A failed outgoing subscriber-card delivery logs **only the exception class**,
not the recipient's Telegram chat ID or arbitrary Telegram exception text
(which could contain a bot-token URL). Delivery attempts continue for other
recipients and the provider is shown only the aggregate sent count. The offline
bot smoke injects a synthetic token-bearing transport failure, asserts no
identifier or exception text reaches operator warnings, and verifies that
other recipients still get an attempted delivery. It is not a real Telegram
delivery or external acceptance receipt.

Backend signal-creation results are also untrusted. The bot does not echo
arbitrary `detail` or `parser_error` strings into provider Telegram replies
and does not broadcast a card for malformed or missing signal identifiers.
A contradictory HTTP 200 response containing a `detail` field is also refused
**even when its value is `null`, empty text or an empty list**, and even if
other signal fields appear valid; no recipient lookup or card is authorised.
Because a POST may persist a signal despite a failed response, providers
must check their feed history before retrying an unconfirmed creation.
Offline synthetic negative tests cover secret-bearing and malformed responses;
they do not prove Telegram delivery or broker-demo acceptance.

Bot transport logging is intentionally restricted to WARNING and above for
`httpx` and `httpcore`: HTTPX INFO request diagnostics include Telegram Bot API
URLs containing the bot token. Never enable transport DEBUG/INFO with real bot
credentials. The offline bot smoke checks this using `httpx.MockTransport` and
a synthetic marker (including a negative control). This safeguard does **not**
replace deployed log-review or independent security assurance.
The same offline smoke refuses Python `-O`, `-OO` or `PYTHONOPTIMIZE`,
which would otherwise disable its assertion-based checks and print a false PASS.

## Subscriber invite-response integrity (offline verified only)

The hosted bot's `/join INVITE_TOKEN` flow checks that registration returns the
same active Telegram user before attempting the one-time subscription invite.
An acceptance response counts as confirmed only when the backend returns an
active subscription with nonempty subscription/account/provider/feed identifiers
and names. Malformed or error-shaped HTTP 200 responses never produce a
"Joined" receipt or disclose arbitrary backend `detail` text or invite tokens.
An unconfirmed response may still have consumed an invite, so subscribers should
check membership with their provider before retrying. This is verified using
synthetic offline response fixtures only; no real subscriber or provider was used.

## Subscriber YES/NO decision receipt safety (offline verified only)

A Telegram subscriber's YES/NO callback treats a backend decision POST as
confirmed only when its response contains a known, string-typed decision
result **permitted for the requested YES/NO endpoint**, and no error-shaped
`detail` key. Backend-provided `message`, unknown codes and malformed JSON
roots are never reflected to subscribers. A NO request cannot report a newly
`APPROVED` trade and YES cannot report a newly `REJECTED` response; however,
`ALREADY_APPROVED` remains a valid NO reply when an earlier YES already won.
Known provider/feed pause, tenancy, subscription and missing-account refusals
use fixed, locally controlled wording. An ambiguous POST response may still
have recorded an approval or rejection: the bot instructs the subscriber
to check current trade state before retrying rather than claiming no action.
This is an isolated offline mock test, not an MT5 fill, real Telegram
delivery or external acceptance receipt.

## Provider-source connection receipt integrity (offline verified only)

The one-time `/connectprovider` command now requires a well-formed `ACTIVE`
`TELEGRAM` binding receipt with nonempty binding/provider/feed identifiers and
names before telling the provider the source is connected. Unknown, malformed
or error-shaped HTTP 200 results are not reported as success; arbitrary backend
`detail` text and credentials are never echoed. A connection POST can succeed
even if its response is lost, so an unconfirmed connection must be checked in
the Provider Portal before another token is requested. These are synthetic
bot-handler tests, not evidence of real Telegram delivery or provider acceptance.

## Security properties

- one-time token stored only as SHA-256 hash;
- provider can create tokens only for its own feed;
- provider cannot list/revoke another tenant's source objects;
- bot service credential is required in hosted mode;
- feed symbol/expiry policy is applied during screenshot preview and final signal parsing;
- replay identity is scoped to the binding;
- broadcast recipients come only from active subscriptions to the bound feed;
- no provider-wide shared Telegram credential is required.
