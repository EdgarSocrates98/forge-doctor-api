// NestJS depth fixture: constructor injection, @Body DTO typing,
// @Catch/@UseFilters error contract. No guards or class-validator —
// auth and validation must surface as explicit unknowns.
import { Controller, Get, Post, Body, Catch, UseFilters }
  from '@nestjs/common';
import { CatsService } from './cats.service';
import { CreateCatDto } from './dto';

@Catch()
export class AllExceptionsFilter {
  catch() {}
}

@Controller('cats')
export class CatsController {
  constructor(private readonly cats: CatsService) {}

  @Get()
  findAll() { return this.cats.all(); }

  @Post()
  @UseFilters(AllExceptionsFilter)
  create(@Body() dto: CreateCatDto) { return this.cats.add(dto); }
}
