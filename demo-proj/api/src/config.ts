function required(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`Missing configuration: ${name}`);
  return value;
}
function port(name: string, fallback: number): number {
  const value = Number(process.env[name] ?? fallback);
  if (!Number.isInteger(value) || value < 1 || value > 65535) throw new Error(`Invalid port: ${name}`);
  return value;
}
if (!['true', 'false'].includes(process.env.FIXTURE_MODE ?? '')) throw new Error('Set FIXTURE_MODE explicitly to true or false');
const fixture = process.env.FIXTURE_MODE === 'true';
if (fixture && process.env.NODE_ENV === 'production') throw new Error('Fixture mode is local-only');
export const config = {
  fixture,
  fixtureSecret: fixture ? required('FIXTURE_SECRET') : '',
  databaseUrl: required('DATABASE_URL'),
  port: port('PORT', 3000),
  host: process.env.HOST ?? '127.0.0.1',
  redis: {
    host: process.env.REDIS_HOST ?? 'localhost', port: port('REDIS_PORT', 63799),
    connectTimeout: 5000,
    retryStrategy: (attempt: number) => attempt <= 3 ? Math.min(attempt * 500, 1500) : null,
  },
  supabaseUrl: fixture ? '' : required('SUPABASE_URL'),
  supabaseKey: fixture ? '' : required('SUPABASE_PUBLISHABLE_KEY'),
  supabaseServiceKey: fixture ? '' : required('SUPABASE_SERVICE_ROLE_KEY'),
  streamKey: fixture ? '' : required('STREAM_API_KEY'),
  streamSecret: fixture ? '' : required('STREAM_API_SECRET'),
  expoAccessToken: process.env.EXPO_ACCESS_TOKEN,
};
