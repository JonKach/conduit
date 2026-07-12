# Developing in this Frontend

This project is built on the [FastAPI full-stack template](https://github.com/fastapi/full-stack-fastapi-template). If you've only worked in barebones Create-React-App-style projects, the biggest adjustment is that **routing, data-fetching, and API types are not hand-rolled** — they come from two code generators (TanStack Router and openapi-ts) that watch your code/backend and regenerate files for you. Don't hand-edit generated files; edit the source that feeds them instead.

## Stack at a glance

| Concern | Library |
|---|---|
| Build tool | Vite |
| UI framework | React 19 |
| Routing | [TanStack Router](https://tanstack.com/router) (file-based) |
| Server state / data fetching | [TanStack Query](https://tanstack.com/query) |
| API client | Auto-generated from the backend's OpenAPI schema ([`@hey-api/openapi-ts`](https://heyapi.dev/)) |
| Forms | `react-hook-form` + `zod` (validation) |
| Styling | Tailwind CSS v4 |
| Component primitives | Radix UI, wrapped as [shadcn/ui](https://ui.shadcn.com/)-style components in `src/components/ui` |
| Linting/formatting | [Biome](https://biomejs.dev/) (replaces ESLint + Prettier) |
| E2E tests | Playwright |
| Package manager | Bun (Node also works) |

Run it locally:

```bash
bun install
bun run dev       # http://localhost:5173
```

Other scripts worth knowing (see `package.json`):

```bash
bun run build            # tsc typecheck + vite build
bun run lint              # biome check --write (auto-fixes)
bun run generate-client   # regenerate src/client/ from openapi.json
bun run test               # playwright e2e tests
bun run test:ui            # playwright UI mode
```

---

## 1. The generated API client (`src/client/`)

**Never hand-edit anything in `src/client/`.** It's entirely generated from the backend's OpenAPI schema (`openapi.json` at the project root) by running:

```bash
bun run generate-client
```

This means: whenever the FastAPI backend adds/changes an endpoint or Pydantic model, someone regenerates this client — you don't write fetch calls or DTOs by hand.

What's in there:

- **`types.gen.ts`** — TypeScript types for every request/response shape (e.g. `ItemCreate`, `UserPublic`).
- **`sdk.gen.ts`** — one "Service" class per backend router, each method a typed API call (e.g. `ItemsService.readItems()`, `UsersService.readUserMe()`, `LoginService.loginAccessToken()`). Method names come from the backend's route operation IDs.
- **`core/`** — the underlying Axios-based request plumbing (`OpenAPI` config, `ApiError`, `CancelablePromise`). You'll rarely touch this directly.
- **`index.ts`** — re-exports everything, so you always import from `@/client`.

Example of the shape you'll actually call:

```ts
import { ItemsService, type ItemCreate } from "@/client"

await ItemsService.readItems({ skip: 0, limit: 100 })
await ItemsService.createItem({ requestBody: data as ItemCreate })
```

Auth/base URL config happens once in `src/main.tsx`:

```ts
OpenAPI.BASE = import.meta.env.VITE_API_URL
OpenAPI.TOKEN = async () => localStorage.getItem("access_token") || ""
```

Every generated call automatically attaches the bearer token — you never set headers manually.

**Errors**: failed calls throw `ApiError` (from `@/client`). `src/utils.ts` has `handleError`, a helper you bind to a toast function and pass as a mutation's `onError` (see the Forms section below).

---

## 2. Routing: file-based, with a generated route tree

Routes live in `src/routes/`. TanStack Router's Vite plugin (configured in `vite.config.ts` via `tanstackRouter(...)`) watches this folder and **auto-generates `src/routeTree.gen.ts`** — a big file you should never edit by hand. It's regenerated on every dev-server save/build. `main.tsx` just imports it:

```ts
import { routeTree } from "./routeTree.gen"
const router = createRouter({ routeTree })
```

### How file names map to URLs

| File | Route |
|---|---|
| `src/routes/__root.tsx` | Root layout — wraps *everything*, renders `<Outlet/>`, sets up devtools, global not-found/error components |
| `src/routes/_layout.tsx` | A **pathless layout route** (leading `_` = doesn't add a URL segment). Renders the authenticated app shell (sidebar, header, footer) around its children, and gatekeeps auth in `beforeLoad` |
| `src/routes/_layout/index.tsx` | `/` (dashboard home), rendered inside `_layout` |
| `src/routes/_layout/items.tsx` | `/items` |
| `src/routes/_layout/admin.tsx` | `/admin` |
| `src/routes/_layout/settings.tsx` | `/settings` |
| `src/routes/login.tsx`, `signup.tsx`, etc. | Top-level routes, outside the authenticated shell |

So nesting = folder/file nesting, and a `_`-prefixed segment is a **layout that doesn't appear in the URL**. This is how "must be logged in" is enforced for a whole group of pages at once — see `_layout.tsx`:

```ts
export const Route = createFileRoute("/_layout")({
  component: Layout,
  beforeLoad: async () => {
    if (!isLoggedIn()) throw redirect({ to: "/login" })
  },
})
```

Any route nested under `_layout/` inherits this check for free — you don't add auth logic to each page.

### Anatomy of a route file

```ts
export const Route = createFileRoute("/_layout/items")({
  component: Items,
  head: () => ({ meta: [{ title: "Items - FastAPI Template" }] }),
})

function Items() { /* the page */ }
```

`createFileRoute` is the building block. Common options you'll use:
- `component` — the React component to render
- `beforeLoad` — runs before render; good for auth/redirects
- `loader` — can prefetch data before render (this project mostly fetches inside components via TanStack Query instead, see below)
- `head` — sets `<title>`/meta tags

To add a new page: create a file under `src/routes/_layout/newpage.tsx` following this pattern, save, and the router plugin regenerates `routeTree.gen.ts` for you — the route just appears. No manual registration anywhere.

To navigate: use `useNavigate()` or `<Link to="/items">` from `@tanstack/react-router` (not `<a>` or `react-router-dom`).

---

## 3. Data fetching: TanStack Query

TanStack Query (`@tanstack/react-query`) manages all **server state** — caching, loading/error states, refetching, invalidation. It's set up once in `main.tsx`:

```ts
const queryClient = new QueryClient({
  queryCache: new QueryCache({ onError: handleApiError }),   // auto-logout on 401/403
  mutationCache: new MutationCache({ onError: handleApiError }),
})
```

### Reading data — `useQuery` / `useSuspenseQuery`

Pattern used throughout this codebase (`src/routes/_layout/items.tsx`):

```ts
function getItemsQueryOptions() {
  return {
    queryKey: ["items"],
    queryFn: () => ItemsService.readItems({ skip: 0, limit: 100 }),
  }
}

function ItemsTableContent() {
  const { data: items } = useSuspenseQuery(getItemsQueryOptions())
  return <DataTable columns={columns} data={items.data} />
}

function ItemsTable() {
  return (
    <Suspense fallback={<PendingItems />}>
      <ItemsTableContent />
    </Suspense>
  )
}
```

Key ideas:
- **`queryKey`** — an array that uniquely identifies this data (`["items"]`, `["currentUser"]`). Query results are cached by this key; matching keys elsewhere in the app share the same cache entry.
- **`queryFn`** — calls the generated client. Nothing fancier than "call the SDK method."
- **`useSuspenseQuery`** + `<Suspense fallback={...}>` — this project prefers Suspense-based loading (component just throws while loading, a skeleton/`Pending*` component renders meanwhile) over manually checking `isLoading` everywhere. Plain `useQuery` (with `enabled`, manual `isLoading` checks) is used when a query is conditional — see `useAuth.ts`'s `currentUser` query, which uses `enabled: isLoggedIn()`.

### Writing data — `useMutation`

Pattern used in `src/components/Items/AddItem.tsx`:

```ts
const queryClient = useQueryClient()
const { showSuccessToast, showErrorToast } = useCustomToast()

const mutation = useMutation({
  mutationFn: (data: ItemCreate) => ItemsService.createItem({ requestBody: data }),
  onSuccess: () => {
    showSuccessToast("Item created successfully")
    form.reset()
  },
  onError: handleError.bind(showErrorToast),
  onSettled: () => {
    queryClient.invalidateQueries({ queryKey: ["items"] })
  },
})

mutation.mutate(formData)
```

Key ideas:
- **`mutationFn`** calls a generated SDK method (a POST/PUT/DELETE endpoint).
- **`onSettled` + `invalidateQueries`** — after a mutation finishes (success or failure), invalidate the related `queryKey` so any `useQuery`/`useSuspenseQuery` using it refetches automatically. This is how the items table updates after you add an item — there's no manual "refetch" call or local state sync.
- **`onError: handleError.bind(showErrorToast)`** — the standard error-toast pattern; `handleError` (in `src/utils.ts`) extracts a readable message from the thrown `ApiError` and calls whatever function it's bound to.
- **`mutation.isPending`** drives loading states on buttons (see `LoadingButton`).

### Mental model vs. plain React

If you're used to `useState` + `useEffect` + manual `fetch`: TanStack Query replaces that entirely for anything that comes from the backend. You don't store server data in `useState`, and you don't write `useEffect(() => { fetch(...) }, [])`. You describe *what* data you need (`queryKey`/`queryFn`), and the cache, refetching, and loading/error states come for free. `useState` is still what you reach for for local UI state (is a dialog open, form field values before submit, etc.).

---

## 4. Forms: react-hook-form + zod

Forms (see `AddItem.tsx`, `UserInformation.tsx`, `login.tsx`) follow one consistent pattern:

```ts
const formSchema = z.object({
  title: z.string().min(1, { message: "Title is required" }),
  description: z.string().optional(),
})
type FormData = z.infer<typeof formSchema>

const form = useForm<FormData>({
  resolver: zodResolver(formSchema),
  mode: "onBlur",
  defaultValues: { title: "", description: "" },
})

const onSubmit = (data: FormData) => mutation.mutate(data)

<Form {...form}>
  <form onSubmit={form.handleSubmit(onSubmit)}>
    <FormField
      control={form.control}
      name="title"
      render={({ field }) => (
        <FormItem>
          <FormLabel>Title</FormLabel>
          <FormControl><Input {...field} /></FormControl>
          <FormMessage />
        </FormItem>
      )}
    />
  </form>
</Form>
```

- `zod` defines the validation schema and doubles as the TypeScript type source (`z.infer`).
- `Form`, `FormField`, `FormItem`, `FormControl`, `FormMessage` are from `@/components/ui/form` — thin wrappers around `react-hook-form` that wire up labels/errors/accessibility automatically.
- Submitting typically calls a `useMutation` from the section above — forms and API writes are always paired this way.

---

## 5. Components

- **`src/components/ui/`** — low-level, generic primitives (Button, Dialog, Input, Table, Sidebar, etc.), Radix-based, shadcn-style. Excluded from Biome linting on purpose (treated as vendored/generated-ish). Don't add business logic here — these should stay generic and reusable app-wide.
- **`src/components/Common/`** — shared app pieces (DataTable, AuthLayout, ErrorComponent, NotFound, Footer).
- **`src/components/{Items,Admin,UserSettings,Pending,Sidebar}/`** — feature-specific components, one folder per domain, mirroring the backend's resource grouping. `Pending*` components are Suspense fallbacks (skeletons).
- **`src/components/theme-provider.tsx`** — dark/light theme via `next-themes`.

Path alias: `@/` maps to `src/` (configured in `vite.config.ts` and `tsconfig.json`) — always import as `@/components/...`, `@/hooks/...`, `@/client`, not relative `../../`.

---

## 6. Auth

`src/hooks/useAuth.ts` is the one place auth logic lives:

- `isLoggedIn()` — checks for `access_token` in `localStorage`. Exported standalone (used in route `beforeLoad` guards, outside React).
- `useAuth()` — a hook exposing `user` (current user query), `loginMutation`, `signUpMutation`, `logout`.
- Token storage is plain `localStorage`; `main.tsx` wires `OpenAPI.TOKEN` to read it, and a global query/mutation cache `onError` handler auto-clears the token and redirects to `/login` on any 401/403.

---

## 7. Styling

Tailwind CSS v4, configured via the Vite plugin (`@tailwindcss/vite`) rather than a `tailwind.config.js` — most config lives in `src/index.css` using Tailwind's CSS-based config. Use the `cn()` helper (`src/lib/utils.ts`, `clsx` + `tailwind-merge`) whenever you're conditionally combining class names:

```ts
<div className={cn("base-classes", isActive && "text-primary", className)} />
```

---

## 8. Typical workflow: adding a new feature backed by a new endpoint

1. Backend adds/changes an endpoint (new FastAPI route + Pydantic schema).
2. From the frontend: `bun run generate-client` (needs `openapi.json` refreshed from the backend — see README "Generate Client" section) → new types/methods appear in `src/client`.
3. Add a `queryFn`/`mutationFn` using the new `XService.method`.
4. Wire it into a component with `useQuery`/`useSuspenseQuery` (reads) or `useMutation` (writes), invalidating related `queryKey`s on success.
5. If it's a new page, add a file under `src/routes/_layout/` (or `src/routes/` if it shouldn't require auth) — the router plugin picks it up automatically.
6. Run `bun run lint` before committing (Biome auto-fixes most style issues).

---

## 9. Testing

Playwright E2E tests live in `tests/*.spec.ts`, run against a real dev server. `tests/utils/` has helpers for creating random users/items and hitting a "private" test-only API for setup/teardown. `tests/auth.setup.ts` logs in once and reuses the session across specs. Run with `bun run test` (headless) or `bun run test:ui` (interactive).
