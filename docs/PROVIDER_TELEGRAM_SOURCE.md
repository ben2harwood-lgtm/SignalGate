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

## Administrator `/testsignal` private-chat boundary (offline guard)

Even an authorised administrator must submit the manual demo-only `/testsignal`
command in a private Telegram chat. Group, supergroup, channel and missing-chat
requests are refused **before** checking administrator identity, parsing command
text, submitting a signal or enumerating/sending subscriber cards. The refusal
contains no submitted text or source details. A private administrator command
continues through the existing authenticated, tenant-scoped demo-only path;
private non-admin users still receive "Admin only." Synthetic offline cases
exercise these paths; they do not demonstrate real Telegram delivery or
MT5 demo-broker execution.

## Administrator `/lastsignals` history privacy (offline guard)

`/lastsignals` also requires a private chat, even for an administrator.
Group/supergroup/channel or missing-chat requests are refused before an admin
identity check or backend history retrieval, with no signal IDs, symbols or
submitted text reflected. Existing private admin history and private non-admin
rejection remain intact. These protections have isolated synthetic handler
tests only; they are not Telegram delivery or MT5 broker-demo receipts.

## /status health-receipt safety (offline checks; external HOLD)

Private Telegram `/status` is a read-only display, not a release
acceptance or readiness probe. An HTTP-200 `/health` response counts as
verified only when it is an error-free mapping with `status="ok"`,
a real boolean `demo_only_mode` and a real boolean `admin_paused`.
Malformed arrays, diagnostic/error payloads, missing fields, bool-like
numbers and strings must display `unknown` for the safety fields and
a generic health-unconfirmed warning; untrusted server text is not echoed.
A structurally valid receipt reporting demo-only mode **disabled** is
displayed with an explicit *do not trade* warning, never as permission
to execute. Group, supergroup, channel and missing-chat requests remain
refused before backend calls. `/status` now shows the Telegram ID with an
explicit **registration not checked** label, rather than asserting that
registration succeeded. The local role hint and an ACTIVE provider-source
binding are not evidence of subscriber registration or release acceptance.

Backend-managed provider/feed display names and feed IDs are untrusted even
after source-binding checks. The read-only `/status` renderer bounds each
field to 80 characters and rejects control, invisible format/bidi,
surrogate and line/paragraph separator characters. Invalid labels display
`unavailable`, never backend diagnostic text or injected `Demo only mode` /
`Admin paused` lines. Ordinary safe Unicode names remain displayable.
The label guard does **not** change binding authority, provider permission,
backend calls or trading controls; it also does not prove that visually
similar Unicode letters are impossible. This is a presentation boundary.

The registered offline smoke contains negative and positive synthetic
receipts and no network/broker contact. Even a passing CI test does not
establish actual MT5 demo-broker, deployed health monitoring, independent
assurance or external acceptance. Frozen RC2 and all release holds remain.

## `/join` and `/connectprovider` reply-label integrity (offline guard)

A backend-confirmed, typed ACTIVE subscription or Telegram source connection
is evidence of the recorded membership/binding, **not** authority to print
arbitrary provider/feed labels. The private `/join` and `/connectprovider`
success replies now apply the same display-only 80-character, raw Unicode
control/format/line-separator guard as `/status` to the chosen provider name
and feed name. An unsafe label renders `unavailable`; it cannot insert a
forged safety line, one-time credential label or backend diagnostic.

The guard does not change registration, one-time invite consumption,
provider/feed authority, source binding, HTTP methods or retry behaviour.
A valid one-time EA licence is still shown **only** in the existing private
join reply; a failed/ambiguous POST must still be reconciled before retry.
The registered offline smoke extends the existing join and connection
receipt checks with hostile names and benign Unicode examples. These are
synthetic display checks, not actual Telegram delivery, broker-demo evidence
or independent security acceptance. Frozen RC2 and the release HOLD remain.

## `/settings` configuration privacy (offline guard)

The `/settings` command now requires a private Telegram chat **before**
requesting protected admin settings or public health fallback. Group,
supergroup, channel and missing-chat requests receive generic guidance with
no backend lookup, configuration values or submitted text reflected.
Existing private admin settings and private generic fallback remain unchanged.
This guard has synthetic offline positive/negative coverage only, not
real Telegram delivery, MT5 broker-demo testing or external acceptance.

## Administrator `/lastcommands` metadata privacy (offline guard)

`/lastcommands` is private-chat-only even for an administrator. A group,
supergroup, channel or missing-chat update is refused before checking the
administrator identity, sending its credentials or querying backend command,
execution and management counts. Refusals reveal no counts or command text.
Private administrators retain the authenticated status-count path, while
private non-admin users still receive the generic denial. Negative and
positive synthetic offline tests cover these boundaries; they do not establish
actual Telegram delivery, MT5 broker-demo acceptance or external assurance.

## Administrator `/users` count privacy (offline guard)

The `/users` administrator command must be sent in a private Telegram chat.
Group, supergroup, channel and missing-chat requests are refused before
administrator identity, credential/header creation or backend `/admin/status`
access. Refusals contain no user count or submitted text. Private administrators
retain the existing approximate count response; private non-admin users remain
denied. Adversarial and positive checks use synthetic offline handlers only,
not real Telegram delivery, MT5 broker-demo or external acceptance.

## Screenshot-preview callback privacy (offline guard)

Confirm, Edit and Cancel screenshot buttons are accepted only in a private
Telegram chat. A group, supergroup, channel, unknown-type or missing-chat callback
gets an ephemeral alert visible to the clicker, **without reading or editing the
shared message**, before provider-source lookup, pending-preview state changes
or signal creation/broadcast. An existing private preview remains unchanged on
a shared-chat refusal; its text, source and tokens are not echoed. Offline
adversarial tests cover all three actions and five non-private chat shapes.
This is synthetic handler evidence only, **not** proof of real Telegram callback
delivery, a broker-demo trade, independent assurance or release acceptance.

## Screenshot edit-text privacy (offline guard)

A user's pending private screenshot edit can persist in Telegram user-scoped
bot state. Ordinary text in other chats is ignored, and text sent from a
group/supergroup/channel or a message with missing chat metadata cannot consume
that private preview, fetch provider-source authority or create/broadcast a
signal. When a shared-chat text arrives while an edit is pending, the bot gives
generic private-chat guidance without echoing either text, source details or
pending tokens; the private candidate stays available for a private correction.
The protection has synthetic offline positive/negative coverage, not real
Telegram delivery or external acceptance evidence.

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
Subscriber targets must be canonical, positive Telegram **user** IDs, not
negative group/channel chat IDs. The bot refuses zero, negative, leading-zero,
non-ASCII, non-decimal, non-string and out-of-range (>52-bit) identities before
sending **any** card from that recipient list, even if earlier entries are valid.
This is an offline-tested routing boundary, not a substitute for backend tenancy.

The bot separately validates a persisted VALID signal's visible card fields
before building any subscriber approval card or querying recipients: bounded
single-line ASCII symbols, BUY/SELL and an explicit entry shape. MARKET must
have no non-null entry price; LIMIT must have a finite positive numeric entry
price. Finite positive numeric SL/TP and optional price levels are checked too.
LIMIT display remains a preview; the demo EA separately refuses LIMIT execution. Missing required SL/TP1, booleans,
non-finite/huge numbers, injected line breaks and Unicode format controls fail
closed with generic provider-history guidance. A successful signal-creation
HTTP status alone never authorises an unverified display. In hosted mode the
card expiry policy duration is derived from persisted signal `created_at` and
`expires_at` (UTC ISO-8601), rather than the preceding source-status policy.
An operator's expiry-policy update between status GET and signal creation POST
therefore cannot make the bot show the stale policy duration. Missing, malformed,
inconsistent, implausible or already-expired timestamps refuse the card before
recipient lookup. The bot evaluates the persisted deadline against its UTC clock
and fails closed on stale receipts or creation timestamps more than one
minute ahead of the bot's UTC clock. This small skew allowance does not extend
the persisted expiry; backend/bot host clock synchronisation is required.
Offline coverage simulates source status at five minutes and persisted signal
expiry at 23 minutes, plus fail-closed malformed receipts. The displayed
card explicitly calls this the expiry window measured **from signal creation**,
not an "expires in" countdown. The bot rechecks the persisted deadline
after recipient lookup and before each hosted subscriber send; if it expires
mid-batch, further sends stop and the provider sees the number of
Telegram API-acknowledged card submissions rather than a claim that messages
were delivered. A zero count means no successful API acknowledgement; it does
not establish that subscribers received nothing after a transport error.
A Telegram send in progress may still complete after expiry: this is not an
atomic revocation guarantee. Transport or replay latency can reduce the
remaining approval time. A Telegram transport error does not prove that a
subscriber card was not accepted: the bot does not automatically retry, and
its provider summary distinguishes API-accepted card submissions from
unconfirmed attempts, including expiry-interrupted batches. Operators must
confirm uncertain delivery with affected subscribers before manually resending.
Counts are not proof of actual Telegram delivery. Even when every send
returns without an exception (including an empty subscriber list), the
provider summary reports Telegram API-accepted submissions, **not** confirmed
subscriber delivery.
This is an isolated synthetic Telegram guard; no actual recipient delivery, MT5 broker-demo,
independent pentest or release acceptance is inferred.

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
identifiers and names. The status response carries the **effective expiry**
used by server-side signal parsing: the feed override, or the same database-backed
default used by the parser when no override is configured (including any
operator-managed setting). It must not report only the environment default when
a persisted setting overrides it. The bot accepts only an exact integer from 1
through 1440; missing/null, boolean, float, string, zero, negative or
over-limit expiry values fail closed before screenshot extraction or signal
creation, so a human approval card cannot claim an expiry different from the
server policy. An HTTP 200 with an array, error detail, revoked binding, other
source type or incomplete fields is **not** authority to submit a screenshot;
an existing confirmable preview is invalidated instead. A stale local-demo
provider ID cannot override this hosted refusal. The backend's authenticated,
tenant-bound lookup is still authoritative, and the bot never treats an
identifier/header alone as authentication. Synthetic offline tests exercise
malformed, revoked, expiry-boundary and valid cases without Telegram or broker
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

Backend signal-creation results are also untrusted. Even when the parser
returns `VALID`, a persisted signal receipt must have ledger `status: VALID`
to authorise a new subscriber card. The backend may return an existing signal
for a duplicate source message; if its state has since become `EXPIRED`,
it must not be re-broadcast. Missing, malformed, rejected or expired status
receipts fail closed before recipient lookup, with provider-history guidance.
The hosted Telegram signal route also refreshes expiry on duplicate-source
responses. A previously VALID signal past its deadline becomes EXPIRED before
the bot can consider another card; its id and original deadline are preserved,
and repeated replays do not duplicate the expiry audit event. SQLite and
PostgreSQL regression checks cover this server-side temporal guard. These
offline checks do not prove Telegram/broker delivery or atomic
expiry/rebinding assurance.

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

## Administrator /lastsignals history receipt boundary (offline test contract)

The administrator's private-chat /lastsignals command reads GET /signals/recent
exactly once. The canonical backend returns an array of signal summaries, with
required ID, parser-status and lifecycle-status strings and optional symbol
and direction. Never treat a successful HTTP response, a map-shaped error or
partial/malformed history row as confirmed history. Display at most ten rows,
with printable ASCII strings bounded to 64 characters; reject error/detail
fields, control characters, Unicode spoofing, wrong types and malformed rows
before displaying any of the returned history. A missing backend response or
genuinely empty array keeps the existing no-history/unreachable message.

The registered isolated smoke tests invalid roots, individual fields, mixed
good/bad rows, private positive results, nullable optional fields and the ten
row display cap. This is a broker-free test contract, not proof of actual
Telegram delivery, MT5 demo acceptance, external assurance or release approval.
No POST, retry, trading-mode change, new backend credential or shared-chat
access is introduced.

## Administrator /settings response integrity (offline test contract)

The private-chat /settings handler queries GET /admin/status once. Only an
explicit HTTP **401/403** from this protected endpoint permits a single
GET /health fallback, with generic defaults shown only after a typed
demo_only_mode=true health receipt. The HTTP client now returns an internal
denial sentinel for this narrow case; a failed connection, 4xx other than
401/403, 5xx, malformed/invalid JSON, null or scalar HTTP-2xx response is
**not** evidence of non-admin refusal and yields unconfirmed guidance with
**no** /health request. Administrator settings
are displayed only from an error-free mapping with demo_only_mode=true.
Displayed numeric tokens are bounded nonnegative decimal values; the
split-ticket flag is a typed boolean or true/false string. Missing numeric
settings are explicitly "not set". Malformed, control-bearing, overly long,
nested or error-shaped values yield generic unconfirmed guidance without
exposing backend diagnostics or guessed operating status. Shared chats still
reach neither backend endpoint. The offline smoke tests real HTTP helper
classification with a mock transport (401/403 refusal, other HTTP errors,
invalid JSON, null/scalar/list 2xx, connection failure, valid admin) as well
as direct handler fixtures; no external request is made. No backend POST,
retries, account operation, Telegram delivery or external acceptance is
claimed. These are synthetic offline regressions only.

## Administrator /lastcommands count receipt integrity (offline verified only)

The private-chat administrator `/lastcommands` command reads `GET /admin/status`
once. The response must contain all three `counts.commands`,
`counts.executions` and `counts.management_events` as genuine nonnegative
signed 64-bit integers. Missing, malformed, wrong-type, negative, overflowing,
partial or top-level `detail`/`error` responses yield generic **unconfirmed**
guidance, not invented counts or reflected backend diagnostics. There is no
automatic retry, mutation or additional credential exposure.

The registered hosted Telegram offline smoke exercises each counter with
adversarial payloads, valid zero/nonzero receipts, and exactly one GET per
authorised private request; the existing shared-chat and non-admin refusal
checks remain. This is synthetic test coverage only, not actual Telegram
delivery, MT5 broker-demo evidence or independent external assurance.

## Administrator /users count receipt integrity (offline verified only)

The private-chat `/users` command reads `GET /admin/status` once after
administrator authorisation. An HTTP 200 alone cannot confirm a user count:
`counts.users` must be a genuine nonnegative signed 64-bit integer, not a
bool, float, string, list or missing field. An error-shaped `detail`/`error`
response, malformed JSON or invalid count yields generic **unconfirmed**
guidance without reflecting server diagnostics or inventing zero users.
No mutating call, retry or credential disclosure is introduced.

Registered isolated Telegram smoke covers 19 synthetic invalid responses,
positive zero/17 counts, a single admin GET and forbidden backend mutation.
Existing private administrator results remain unchanged. This is not actual
Telegram delivery, MT5 broker-demo evidence or independent assurance.

## Administrator emergency pause response integrity (offline verified only)

The `/pause` emergency-stop command is intentionally **not** restricted to
private chats: a valid administrator may issue it from group, supergroup,
channel or missing-chat contexts. Administrator authentication is still required.
No extra pause or resume request is generated by this response check.

The bot only says "Trading paused." when `POST /admin/pause` returns the
exact typed receipt `{"status": "ok", "admin_paused": true}` provided by
`backend/app/routes/admin.py`. Missing responses, error-shaped HTTP 200
JSON, extra keys, contradictory states and non-boolean values result in
generic **unconfirmed** guidance without reflecting backend diagnostics.
The pause might already have committed before a response was lost; operators
should verify authoritative administrative state instead of assuming failure
or blindly repeating a request. No automatic retries were introduced.

Adversarial offline cases cover positive and malformed receipts, shared and
unknown chats, non-admin refusal, and exactly one POST for each admin attempt.
This establishes neither Telegram delivery nor MT5 demo-broker, independent
security or external acceptance. The `/resume` private-chat restriction is
unchanged; frozen RC2 and all release HOLDs remain intact.

## Administrator resume safety boundary (offline verified only)

The Telegram `/resume` command removes an administrative pause. A request
from a group, supergroup, channel or unknown chat is refused **before**
administrator identity lookup, credential creation or `POST /admin/resume`.
A private-chat administrator can still resume; a private non-administrator
remains denied. Offline negative tests prove no state-change request is sent
from a shared/unknown chat, but not actual Telegram delivery or broker state.

A successful HTTP status alone is **not** confirmation that the protective
pause was lifted. The bot only displays "Trading resumed." for the exact typed
backend `/admin/resume` JSON receipt
`{"status": "ok", "admin_paused": false}`. An error-shaped or
extra-field response, wrong pause state, malformed value or uncertain transport
result instead receives generic **unconfirmed** guidance without echoing server
diagnostics. The backend may have committed before a response was lost, so
the operator must verify authoritative admin pause state before relying on it
or retrying; the bot does not automatically repeat the request.

This narrow guard intentionally **does not change `/pause`**, because
restricting an emergency stop needs its own safety/operability review.
The receipt check only has synthetic offline adversarial coverage; it does not
approve execution, release frozen RC2, or replace MT5 demo-broker or independent
external-assurance evidence.

## Private-chat boundary for one-time credentials (offline verified only)

The Telegram bot handles `/start` registration, `/join INVITE_TOKEN` and
`/connectprovider CONNECTION_TOKEN` **only in a private chat** with the bot.
Group, supergroup, channel and missing/unknown chat contexts fail closed
**before any registration, invitation-acceptance or source-connection POST**.
The bot sends only a generic private-chat instruction, without displaying an
EA licence or echoing an invite/source token. A token pasted into a shared
chat may already have been exposed to others, so obtain a replacement rather
than reusing that exposed one-time token. Valid private-chat flows remain
unchanged. `/status` also requires a private chat because the response can
identify the requester's account role, Telegram ID and provider/feed binding;
shared chats receive only a generic instruction **before** either `/health`
or provider-source status is queried. Offline tests cover these refusal paths;
this does not establish actual Telegram delivery or external acceptance.

## Screenshot help source-status privacy (offline verified only)

The `/screenshothelp` command checks whether a provider source is connected
before showing the screenshot workflow. Group, supergroup, channel and missing
chat contexts now receive only generic private-chat guidance **before** any
provider-source lookup. Private connected-source instructions and private
unconnected-source denial remain unchanged. Offline negative/positive mocks
cover these paths; they do not prove actual Telegram delivery, provider
authorisation outside the handler, broadcast safety or broker-demo acceptance.

## Provider screenshot upload privacy (offline verified only)

Photos and image documents sent to SignalGate must arrive in a **private chat**.
Group, supergroup, channel and missing/unknown chats receive a generic refusal
before provider-source lookup, Telegram file download, image extraction or any
pending-preview mutation. Existing private-chat upload/size/transport tests still
apply. These are offline handler checks, not real Telegram delivery or permission
to broadcast or trade; callback and edit-message privacy require their own
separate verification.

## /start connected-source display boundary (offline verified only)

A private Telegram `/start` for an existing ACTIVE, typed provider/feed
source must treat the backend's provider display name, provider-name fallback
and feed name as untrusted presentation data. The names use the same
length-bounded Unicode control/separator rejection as `/status`,
`/join` and `/connectprovider`; unsafe labels show `unavailable` instead
of injecting extra safety or account-state lines. An ACTIVE binding remains
the separate prerequisite for the provider greeting; formatting does not
alter tenancy, membership or source authority. Shared/unknown chats are
refused before any backend read, registration or one-time credential handling.
Offline tests cover these paths without a live Telegram connection, MT5 broker
or independent external acceptance.

## /start registration receipt privacy (offline verified only)

The hosted bot must not display a newly issued one-time EA licence based only
on an HTTP 200 from registration. The response must confirm the exact Telegram
user identity, a nonempty internal user ID and ACTIVE status, with no error
detail field; a licence value must be a bounded printable ASCII string (or absent). A malformed,
other-user, inactive or error-shaped response produces generic operator guidance,
not a false registration receipt or disclosure of backend diagnostics. An
ambiguous registration may already have issued a one-time key, so the provider
or operator should inspect the account rather than assume that retrying will
recover it. Offline synthetic negative and positive cases do not establish
real Telegram delivery, broker-demo acceptance or external assurance.

## Subscriber invite-response integrity (offline verified only)

The hosted bot's `/join INVITE_TOKEN` flow checks that registration returns the
same active Telegram user and a bounded printable ASCII one-time licence (or
no licence) before attempting the one-time subscription invite. Malformed,
oversized, control-character or Unicode licence values refuse the join before
the invite is submitted; the registration POST itself may still have consumed
a newly issued key. An acceptance response counts as confirmed only when the
backend returns an
active subscription with nonempty subscription/account/provider/feed identifiers
and names. Malformed or error-shaped HTTP 200 responses never produce a
"Joined" receipt or disclose arbitrary backend `detail` text or invite tokens.
An unconfirmed response may still have consumed an invite, so subscribers should
check membership with their provider before retrying. This is verified using
synthetic offline response fixtures only; no real subscriber or provider was used.

## Subscriber YES/NO private-chat decision boundary (offline verified only)

Trade-card YES/NO callbacks are **private subscriber-chat only**. When a callback
arrives from a group, supergroup, channel, inline message without an associated
chat, or an unknown/missing chat type, the bot displays a generic private-chat
alert to the clicker **without editing the shared card**. Rejection occurs before
reading subscriber identity or trade-card text, parsing the signal identifier,
creating registration headers or making a decision POST. A valid private-chat
subscriber retains the existing explicit YES/NO backend decision flow; no
automatic approval or retry has been added.

The isolated hosted Telegram offline smoke checks these negative cases against
forbidden backend/identity calls and retains the private YES/NO receipt and
malformed-ID regressions. This is **not** actual Telegram delivery, broker-demo
execution evidence, independent security assurance or release approval. The
subscriber-authorisation path remains execution-critical and draft/HOLD until
independent review and actual controlled MT5 demo-broker acceptance.

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

Telegram callback data is treated as untrusted even when it resembles an
existing inline button: decision callbacks require `YES` or `NO` and an
ASCII `SIG-[A-Z0-9]{1,32}` identifier (including historical numeric demo
IDs). Non-string, delimiter-bearing, Unicode-lookalike and overlong IDs
are refused before any backend decision POST. A malformed signal identifier
in a nominally valid create receipt also blocks subscriber-card delivery.
These guards are verified by offline adversarial fixtures only; they do not
establish real Telegram or MT5 broker acceptance.

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
- the backend recipient receipt filters out noncanonical or nonpositive Telegram
  user IDs, including group/channel IDs, leading-zero/Unicode identifiers and
  values over Telegram's 52-bit user-ID limit; the bot independently rejects
  any malformed recipient entry before sending even one card;
- no provider-wide shared Telegram credential is required.
