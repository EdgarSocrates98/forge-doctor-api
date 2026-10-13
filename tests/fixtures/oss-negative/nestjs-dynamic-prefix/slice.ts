import { Controller, Get } from '@nestjs/common';

const PREFIX = process.env.API_PREFIX ?? 'cats';

@Controller(PREFIX)
export class CatsController {
  @Get()
  findAll() {
    return [];
  }
}
