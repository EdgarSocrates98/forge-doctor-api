# Framework capability depth

Beyond route extraction (see `docs/framework-adapters.md`), each adapter
exposes five capability surfaces through the §39 `discover_*` protocol —
`auth`, `dependencies`, `error_handlers`, `schemas`, `validation`. Every
item carries `file:line` evidence; a surface with no extractable
idiom-static evidence returns an explicit `UnknownFact` — never a
fabricated zero, never silence.

Lab coverage: `labs/frameworks/<framework>-depth/` runs the `frameworks`
pipeline (opt-in via `run: [frameworks]`), which folds surface items into
`capability:<framework>:<kind>:<label>` entities and surface unknowns
into issues.

## FastAPI (`fastapi`, Python `ast`)

| Dimension | Idioms detected | UNKNOWN when |
| --- | --- | --- |
| auth | `Security(dep)`/`OAuth2*` param wrappers → `auth-dependency` | no security params |
| dependencies | `Depends(x)` params → `dependency`; `dependencies=[Depends(x)]` targets → `depends-target` | none |
| error contract | `@app.exception_handler(X) fn` → `error-handler`; `raise HTTPException(status_code=…)` → `http-error` | neither present |
| schemas | body `Annotated`/`request_schema`, `response_model=`/return annotation → `request-schema`/`response-schema` | no typed bodies |
| validation | `Query/Path/Body/Field/Param/Cookie/Header` param defaults → `bound-param` | no bound params |

## Spring Boot (`spring`, Java `textscan`)

| Dimension | Idioms detected | UNKNOWN when |
| --- | --- | --- |
| auth | `@PreAuthorize`/`@PostAuthorize` → `auth-expression`; `@Secured`/`@RolesAllowed` → `auth-roles` | none present |
| dependencies | `@Autowired`/`@Inject` → `injection`; `@Bean` → `bean-factory`; `@Qualifier` → `qualifier` | none present |
| error contract | `@ExceptionHandler` → `error-handler`; `@(Rest)ControllerAdvice` → `advice-class` | none present |
| schemas | `@RequestBody` marker → `request-schema`; its declared param type (incl. generics like `List<PetDto>`) → `request-schema-type` | no `@RequestBody` params |
| validation | `@Valid`/`@Validated` → `validation-marker`; `@NotNull`/`@Size`/`@Min`/`@Max`/`@Pattern` → `constraint` | none present |

## NestJS (`nestjs`, TS `textscan`)

| Dimension | Idioms detected | UNKNOWN when |
| --- | --- | --- |
| auth | `@UseGuards` → `guard`; `@SetMetadata` → `metadata`; `@Roles` → `roles`; `@Public` → `public-marker` | none present |
| dependencies | `constructor(private readonly x: Type)` params → `injected-provider`; `@Inject` → `injection`; `@Injectable` → `provider` | none present |
| error contract | `@Catch` → `exception-filter`; `@UseFilters` → `filter` | none present |
| schemas | `@Body`/`@Query`/`@Param` markers → `request-schema`/`bound-param`; the decorated param's declared type → `request-schema-type` | none present |
| validation | `@UsePipes` → `pipe`; class-validator `@IsString`/`@IsInt`/`@IsOptional`/`@Min`/`@Max`/`@Length` → `constraint` | none present |

## Express (`express`, JS `textscan`)

Express has no decorators — evidence is call-shape based, gated on
module imports where the bare name is ambiguous.

| Dimension | Idioms detected | UNKNOWN when |
| --- | --- | --- |
| auth | imports of `passport`, `express-jwt`, `express-session`, `jsonwebtoken`, `@auth0/express-openid-connect`, `basic-auth`, `cookie-session` → `auth-module`; gated calls `passport.authenticate()`, `expressjwt()`, `jwt.verify()/sign()`, `requiresAuth()`, `cookieSession()` → `auth-middleware` | no auth module imported |
| dependencies | `app.set("k", v)`/`x.locals.k` writes → `app-registry`; `req.app.get("k")` → `registry-read` | no registry idiom |
| error contract | `function f(err, req, res, next)` (err-first, 4+ params) → `error-middleware`; the function passed to `.use()`/route calls → `error-middleware-registration`; inline `(err, …) =>` args → `inline-error-middleware` | no err-first middleware |
| schemas | no Express idiom for declared request schemas — `@Body` decorators only fire in files that also carry decorator syntax (mixed NestJS/Express files report them under both adapters) | plain Express: always UNKNOWN |
| validation | imports of `express-validator`, `zod`, `joi`, `yup`, `ajv` → `validation-module`; their call heads (`body()`, `check()`, `z.object()`, `Joi.object()`, `yup.object()`, `.validate()`, `.parse()`, `.safeParse()`) → `validation-call` — only when the file imports the module | no validator module imported |

### Middleware

`discover_middleware` for Express extracts **top-level** arguments of
`.use()` calls: bare identifiers (`app.use(errHandler)` → `errHandler`)
and factory calls (`app.use(passport.initialize())` →
`passport.initialize()`). Identifiers inside an inline arrow body can
never leak into the surface — they are not a registration site.

## Adversarial posture

All four adapters share the same guarantee: commented-out annotations
(`// @PreAuthorize(...)`), decorator-looking comments
(`// app.use(passport…)`), and idioms inside string literals produce
**zero** items — `ast` never sees comments, and `textscan` blanks
comment/string interiors before pattern matching. Gated calls (e.g.
`body()` for express-validator) require the backing module import in
the same file, so a bare `body(x)` in an unrelated file is not
validation evidence.
