import { Body, Controller, Get, Param, ParseUUIDPipe, Post, Put, Query, Req, UseGuards, NotFoundException } from '@nestjs/common';
import { AuthGuard, AuthRequest, fixtureToken } from './auth';
import { BlockDto, DiscoveryDto, FixtureSessionDto, MessageDto, ProfileDto, PushDto, SwipeDto } from './dto';
import { FlatPal } from './flatpal';
import { Photos } from './providers';
import { fixturePeople } from './fixtures';
import { config } from './config';
@Controller()
@UseGuards(AuthGuard)
export class ControllerApi {
  constructor(private readonly app: FlatPal, private readonly photos: Photos) {}
  @Get('me/profile') profile(@Req() r: AuthRequest) { return this.app.profile(r.userId); }
  @Put('me/profile') save(@Req() r: AuthRequest, @Body() b: ProfileDto) { return this.app.saveProfile(r.userId, b); }
  @Get('discovery') discover(@Req() r: AuthRequest, @Query() q: DiscoveryDto) { return this.app.discover(r.userId, q); }
  @Post('swipes') swipe(@Req() r: AuthRequest, @Body() b: SwipeDto) { return this.app.swipe(r.userId, b); }
  @Get('matches') matches(@Req() r: AuthRequest) { return this.app.matches(r.userId); }
  @Get('matches/:id/messages') messages(@Req() r: AuthRequest, @Param('id', new ParseUUIDPipe({ version: '4' })) id: string) { return this.app.messages(r.userId, id); }
  @Post('matches/:id/messages') send(@Req() r: AuthRequest, @Param('id', new ParseUUIDPipe({ version: '4' })) id: string, @Body() b: MessageDto) { return this.app.send(r.userId, id, b.text); }
  @Post('blocks') block(@Req() r: AuthRequest, @Body() b: BlockDto) { return this.app.block(r.userId, b.targetId); }
  @Post('me/photo-upload') photo(@Req() r: AuthRequest) { return this.photos.upload(r.userId); }
  @Put('me/push-token') push(@Req() r: AuthRequest, @Body() b: PushDto) { return this.app.pushToken(r.userId, b.token); }
  @Get('me/notifications') notifications(@Req() r: AuthRequest) { return this.app.notifications(r.userId); }
}
@Controller()
export class PublicApi {
  @Get('health/live') live() { return { live: true, mode: config.fixture ? 'fixture' : 'live' }; }
  @Get('fixture/users') users() {
    if (!config.fixture) throw new NotFoundException();
    return fixturePeople.map(({ id, name }) => ({ id, name }));
  }
  @Post('fixture/session') session(@Body() b: FixtureSessionDto) {
    if (!config.fixture) throw new NotFoundException();
    return { mode: 'fixture', accessToken: fixtureToken(b.userId), expiresIn: 3600 };
  }
}
