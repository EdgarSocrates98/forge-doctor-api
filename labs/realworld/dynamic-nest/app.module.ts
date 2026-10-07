import { Module } from '@nestjs/common';
// Dynamic module registration — no static routes.
const providers = [process.env.SERVICE || DefaultService];
@Module({ providers })
export class AppModule {}
