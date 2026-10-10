import { CanActivate, ExecutionContext, Injectable, UnauthorizedException, ServiceUnavailableException } from '@nestjs/common';
import { createHmac, timingSafeEqual } from 'node:crypto';
import { config } from './config';
import { fixturePeople } from './fixtures';
import { object, providerFetch, providerJson, uuidPattern } from './http';
export type AuthRequest = { headers: { authorization?: string }; userId: string };
export function fixtureToken(id: string): string {
  if (!config.fixture || !fixturePeople.some(p => p.id === id)) throw new UnauthorizedException('Unknown fixture user');
  const payload = Buffer.from(JSON.stringify({ sub: id, exp: Math.floor(Date.now() / 1000) + 3600 })).toString('base64url');
  return `${payload}.${createHmac('sha256', config.fixtureSecret).update(payload).digest('base64url')}`;
}
function verifyFixture(token: string): string {
  const [payload, signature, extra] = token.split('.');
  if (!payload || !signature || extra) throw new UnauthorizedException();
  const expected = createHmac('sha256', config.fixtureSecret).update(payload).digest();
  const received = Buffer.from(signature, 'base64url');
  if (expected.length !== received.length || !timingSafeEqual(expected, received)) throw new UnauthorizedException();
  let decoded: unknown;
  try { decoded = JSON.parse(Buffer.from(payload, 'base64url').toString()); }
  catch { throw new UnauthorizedException(); }
  if (!object(decoded) || typeof decoded.sub !== 'string' || !fixturePeople.some(p => p.id === decoded.sub)
    || typeof decoded.exp !== 'number' || decoded.exp <= Date.now() / 1000) throw new UnauthorizedException();
  return decoded.sub;
}
@Injectable()
export class AuthGuard implements CanActivate {
  async canActivate(context: ExecutionContext): Promise<boolean> {
    const request = context.switchToHttp().getRequest<AuthRequest>();
    const authorization = request.headers.authorization;
    if (!authorization?.startsWith('Bearer ') || authorization.length > 8192) throw new UnauthorizedException('Bearer token required');
    const token = authorization.slice(7);
    if (config.fixture) request.userId = verifyFixture(token);
    else {
      // Supabase Auth validates signature, expiry, and the user; never trust client-provided IDs.
      const response = await providerFetch(`${config.supabaseUrl}/auth/v1/user`, {
        headers: { apikey: config.supabaseKey, Authorization: `Bearer ${token}` },
      });
      if (response.status === 401 || response.status === 403) throw new UnauthorizedException('Invalid access token');
      const user = await providerJson(response);
      if (!object(user) || typeof user.id !== 'string' || !uuidPattern.test(user.id)) throw new ServiceUnavailableException('Invalid Supabase user response');
      request.userId = user.id.toLowerCase();
    }
    return true;
  }
}
