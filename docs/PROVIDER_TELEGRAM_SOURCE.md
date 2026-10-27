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

## Screenshot extraction failures

The Telegram bot refuses screenshot photos/documents whose reported size exceeds
**5 MiB** *before downloading them*, and checks actual byte length again before
sending them to the backend. Missing size metadata never bypasses the post-download
check; invalid metadata fails closed. An oversize/invalid attempt clears the
previous pending confirmation/edit token. Both backend extraction endpoints also
apply the same 5 MiB limit. These are offline-only resource and stale-preview
boundaries, not Telegram-delivery or broker-demo acceptance.

Each new screenshot attempt invalidates any earlier unconfirmed preview. Hosted mode
rechecks the persisted provider/feed binding immediately before extraction; if it
has been revoked or cannot be verified, extraction stops without falling back to
the local-demo endpoint. Backend error bodies and exception messages are not
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
The source's backend remains responsible for identity, tenant policy,
subscriber consent and idempotent signal processing. The binding here is
an **in-memory preview integrity guard**, not an authentication credential, a
persistent queue or broker execution acceptance evidence. Restarting the bot
invalidates old preview buttons; providers must send a new screenshot.

Bot transport logging is intentionally restricted to WARNING and above for
`httpx` and `httpcore`: HTTPX INFO request diagnostics include Telegram Bot API
URLs containing the bot token. Never enable transport DEBUG/INFO with real bot
credentials. The offline bot smoke checks this using `httpx.MockTransport` and
a synthetic marker (including a negative control). This safeguard does **not**
replace deployed log-review or independent security assurance.
The same offline smoke refuses Python `-O`, `-OO` or `PYTHONOPTIMIZE`,
which would otherwise disable its assertion-based checks and print a false PASS.

## Security properties

- one-time token stored only as SHA-256 hash;
- provider can create tokens only for its own feed;
- provider cannot list/revoke another tenant's source objects;
- bot service credential is required in hosted mode;
- feed symbol/expiry policy is applied during screenshot preview and final signal parsing;
- replay identity is scoped to the binding;
- broadcast recipients come only from active subscriptions to the bound feed;
- no provider-wide shared Telegram credential is required.
