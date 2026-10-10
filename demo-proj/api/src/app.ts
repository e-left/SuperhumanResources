import 'reflect-metadata';
import { Catch, ExceptionFilter, ArgumentsHost, HttpException, Logger, Module, ValidationPipe } from '@nestjs/common';
import { NestFactory } from '@nestjs/core';
import { Db } from './db';
import { FlatPal } from './flatpal';
import { Chat, Photos } from './providers';
import { AuthGuard } from './auth';
import { ControllerApi, PublicApi } from './controller';
@Catch()
class Errors implements ExceptionFilter {
  private readonly logger = new Logger('ApiErrors');
  catch(error: unknown, host: ArgumentsHost) {
    const response = host.switchToHttp().getResponse();
    if (error instanceof HttpException) {
      if (error.getStatus() >= 500) this.logger.error(`HTTP ${error.getStatus()}: provider operation failed`);
      response.status(error.getStatus()).json(error.getResponse());
    } else {
      // Do not log Prisma errors verbatim: they can embed query parameters or connection strings.
      this.logger.error('Unexpected API failure; inspect database availability and schema');
      response.status(500).json({ statusCode: 500, message: 'Internal API failure' });
    }
  }
}
@Module({ controllers: [ControllerApi, PublicApi], providers: [Db, FlatPal, Chat, Photos, AuthGuard] })
export class AppModule {}
export async function createApp() {
  const app = await NestFactory.create(AppModule, { bodyParser: true });
  app.useGlobalPipes(new ValidationPipe({ whitelist: true, forbidNonWhitelisted: true, transform: true }));
  app.useGlobalFilters(new Errors());
  app.enableShutdownHooks();
  return app;
}
