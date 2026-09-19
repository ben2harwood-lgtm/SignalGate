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

## Security properties

- one-time token stored only as SHA-256 hash;
- provider can create tokens only for its own feed;
- provider cannot list/revoke another tenant's source objects;
- bot service credential is required in hosted mode;
- feed symbol/expiry policy is applied during screenshot preview and final signal parsing;
- replay identity is scoped to the binding;
- broadcast recipients come only from active subscriptions to the bound feed;
- no provider-wide shared Telegram credential is required.
