import { createApp } from './app';
import { config } from './config';
async function main() {
  const app = await createApp();
  await app.listen(config.port, config.host);
  console.log(`FlatPal API listening on ${config.port}; mode=${config.fixture ? 'fixture' : 'live'}`);
}
main().catch(() => { console.error('API startup failed; check configuration, database and port availability'); process.exitCode = 1; });
