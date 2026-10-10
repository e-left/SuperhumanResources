# Package compatibility

Checked on 2026-10-10 using npm package metadata and official documentation, before writing the slice. This is a metadata check, not an installation/runtime result.

| Component | Exact direct pins / choice | Compatibility basis |
| --- | --- | --- |
| Runtime | Node 22.22.3, TypeScript 5.9.3 | Supabase SDK needs Node 22+, React Native needs Node 20.19.4+ |
| Expo | 55.0.31 | Stable SDK chosen deliberately; native dependencies follow its bundled map |
| React / RN | 19.2.0 / 0.83.10 | Expo bundle and RN React peer agree |
| Router | 55.0.18 | Expo bundle; constants/linking and Metro runtime peers pinned alongside it |
| Gestures / animations | 2.30.0 / 4.2.1; worklets 0.7.4 | Expo SDK 55 bundled versions; Reanimated uses the New Architecture |
| TanStack Query | 5.104.1 | React 18/19 peer range |
| NestJS | 11.2.7 | Common/core/platform-express aligned; Node 20+; avoids Nest 12's separate ESM migration |
| Prisma | client and CLI 6.19.0 | Same version; schema datasource URL and CommonJS conventions match Prisma 6 |
| Supabase JS | 2.117.3 | Node 22+; shared client/server SDK version |
| Stream Chat | 9.54.0 | Node 18+; server use only |
| BullMQ | 5.81.5 | Stable major 5, compatible Node runtime; Redis 7 local service |

Sources:
- [Expo 55 native package map](https://unpkg.com/expo@55.0.31/bundledNativeModules.json)
- [Expo 55 Reanimated setup](https://docs.expo.dev/versions/v55.0.0/sdk/reanimated/): Babel configuration is automatic; no separate plugin override needed.
- [Nest migration guide](https://docs.nestjs.com/migration-guide)
- [Prisma unsupported geographic fields](https://www.prisma.io/docs/orm/v6/prisma-client/using-raw-sql/safeql)
- npm registry `version`, `engines`, `peerDependencies` queries for the direct pins.

Exact direct pins live in each `package.json`. Transitive lockfiles must be generated and reviewed on first install. Optional Expo peers and native development build behavior still need validation; do not describe metadata compatibility as a passing build.
