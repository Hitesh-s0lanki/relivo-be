# Clerk Auth Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate Clerk authentication into `relivo-fe-server` with centered sign-in/sign-up pages, protected `/app` and `/onboarding` routes, an auth-aware public Navbar, and a `UserButton` in the app header.

**Architecture:** `ClerkProvider` wraps the root layout; a `(auth)` route group hosts Clerk's prebuilt `<SignIn />` and `<SignUp />` components in a centered layout; `clerkMiddleware` in `src/middleware.ts` protects `/app(.*)` and `/onboarding(.*)`; the public `Navbar` uses `useAuth()` to conditionally render auth CTAs; `MainHeader` gets a `<UserButton />`.

**Tech Stack:** `@clerk/nextjs` v6, Next.js 16 App Router, Sonner v2, TypeScript, Tailwind CSS

---

## File Map

| Action   | Path                                                                 | Purpose                                              |
|----------|----------------------------------------------------------------------|------------------------------------------------------|
| Install  | `package.json`                                                       | Add `@clerk/nextjs`                                  |
| Create   | `.env.local`                                                         | Clerk API keys + redirect env vars (never commit)    |
| Create   | `src/middleware.ts`                                                  | Protect `/app` and `/onboarding` with clerkMiddleware |
| Modify   | `src/app/layout.tsx`                                                 | Wrap with ClerkProvider, add Sonner Toaster           |
| Create   | `src/app/(auth)/layout.tsx`                                          | Centered auth layout, no Navbar/Footer               |
| Create   | `src/app/(auth)/sign-in/[[...sign-in]]/page.tsx`                     | Sign-in page with redirect guard                     |
| Create   | `src/app/(auth)/sign-up/[[...sign-up]]/page.tsx`                     | Sign-up page with redirect guard                     |
| Create   | `src/app/(public)/login/page.tsx`                                    | Redirect `/login` → `/sign-in`                       |
| Create   | `src/app/(public)/signup/page.tsx`                                   | Redirect `/signup` → `/sign-up`                      |
| Create   | `src/app/onboarding/page.tsx`                                        | Post-signup stub, protected by middleware            |
| Modify   | `src/app/(public)/_components/Navbar.tsx`                            | Auth-aware: UserButton + Go to App when signed in    |
| Modify   | `src/app/app/_components/header/MainHeader.tsx`                      | Add `"use client"` + `<UserButton />`                |

---

## Task 1: Install @clerk/nextjs and configure environment

**Files:**
- Modify: `package.json` (via npm)
- Create: `.env.local`

- [ ] **Step 1: Install the package**

Run from `/Users/Hemant/Desktop/projects/relivo/relivo-fe-server`:

```bash
npm install @clerk/nextjs
```

Expected: `@clerk/nextjs` appears in `package.json` dependencies. No peer-dependency warnings about Next.js.

> **Note:** If you see unexpected errors, check `node_modules/next/dist/docs/` — Next.js 16 has breaking changes vs prior versions per `AGENTS.md`.

- [ ] **Step 2: Create .env.local**

Create `/Users/Hemant/Desktop/projects/relivo/relivo-fe-server/.env.local` with this content (fill in real keys from the Clerk dashboard after creating an application at clerk.com):

```
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_test_REPLACE_ME
CLERK_SECRET_KEY=sk_test_REPLACE_ME
NEXT_PUBLIC_CLERK_SIGN_IN_URL=/sign-in
NEXT_PUBLIC_CLERK_SIGN_UP_URL=/sign-up
NEXT_PUBLIC_CLERK_AFTER_SIGN_IN_URL=/app
NEXT_PUBLIC_CLERK_AFTER_SIGN_UP_URL=/onboarding
```

- [ ] **Step 3: Verify dev server still starts**

```bash
npm run dev
```

Expected: Server starts on port 3001 with no import or module errors. Visit `http://localhost:3001` — homepage loads.

- [ ] **Step 4: Commit**

```bash
git -C /Users/Hemant/Desktop/projects/relivo/relivo-fe-server add package.json package-lock.json
git -C /Users/Hemant/Desktop/projects/relivo/relivo-fe-server commit -m "chore: install @clerk/nextjs"
```

---

## Task 2: Add ClerkProvider + Toaster to root layout

**Files:**
- Modify: `src/app/layout.tsx`

Current file has no auth provider and no toast setup. We wrap the entire app in `ClerkProvider` and add `<Toaster />` so toasts work on every route including auth pages.

- [ ] **Step 1: Replace `src/app/layout.tsx` with this content**

```tsx
import type { Metadata } from "next";
import { Plus_Jakarta_Sans, JetBrains_Mono } from "next/font/google";
import { ClerkProvider } from "@clerk/nextjs";
import { Toaster } from "sonner";
import "./globals.css";

const plusJakartaSans = Plus_Jakarta_Sans({
  variable: "--font-sans",
  subsets: ["latin"],
  weight: ["500", "600", "700", "800"],
});

const jetbrainsMono = JetBrains_Mono({
  variable: "--font-mono",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
});

export const metadata: Metadata = {
  title: "Relivo — AI Task Assistant",
  description:
    "Assign tasks, automate workflows, and get things done with Relivo.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <ClerkProvider
      afterSignOutUrl="/sign-in"
      appearance={{ variables: { colorPrimary: "#111827" } }}
    >
      <html
        lang="en"
        className={`${plusJakartaSans.variable} ${jetbrainsMono.variable} h-full antialiased`}
      >
        <body className="min-h-full flex flex-col">
          {children}
          <Toaster richColors position="bottom-right" visibleToasts={3} />
        </body>
      </html>
    </ClerkProvider>
  );
}
```

- [ ] **Step 2: Verify dev server compiles**

```bash
npm run dev
```

Expected: No TypeScript or compilation errors. Homepage still loads at `http://localhost:3001`.

- [ ] **Step 3: Commit**

```bash
git -C /Users/Hemant/Desktop/projects/relivo/relivo-fe-server add src/app/layout.tsx
git -C /Users/Hemant/Desktop/projects/relivo/relivo-fe-server commit -m "feat: add ClerkProvider and Sonner Toaster to root layout"
```

---

## Task 3: Create Clerk middleware

**Files:**
- Create: `src/middleware.ts`

This file runs on every request matching the `matcher` pattern. It calls `auth.protect()` only on `/app` and `/onboarding` routes — all other routes remain public.

- [ ] **Step 1: Create `src/middleware.ts`**

```ts
import { clerkMiddleware, createRouteMatcher } from "@clerk/nextjs/server";

const isProtectedRoute = createRouteMatcher(["/app(.*)", "/onboarding(.*)"]);

export default clerkMiddleware(async (auth, req) => {
  if (isProtectedRoute(req)) await auth.protect();
});

export const config = {
  matcher: [
    "/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)",
    "/(api|trpc)(.*)",
  ],
};
```

- [ ] **Step 2: Verify middleware loads**

```bash
npm run dev
```

Expected: Server starts cleanly. Navigate to `http://localhost:3001/app` — without a session, Clerk should redirect to `/sign-in` (the sign-in page doesn't exist yet so you'll get a 404, but the redirect happening confirms middleware works).

- [ ] **Step 3: Commit**

```bash
git -C /Users/Hemant/Desktop/projects/relivo/relivo-fe-server add src/middleware.ts
git -C /Users/Hemant/Desktop/projects/relivo/relivo-fe-server commit -m "feat: add clerkMiddleware protecting /app and /onboarding"
```

---

## Task 4: Create (auth) route group layout

**Files:**
- Create: `src/app/(auth)/layout.tsx`

Route groups with parentheses don't affect URLs — `(auth)/sign-in/...` maps to `/sign-in`. This layout renders a full-height centered container with no Navbar or Footer.

- [ ] **Step 1: Create `src/app/(auth)/layout.tsx`**

```tsx
export default function AuthLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="flex min-h-dvh items-center justify-center bg-white">
      {children}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git -C /Users/Hemant/Desktop/projects/relivo/relivo-fe-server add src/app/\(auth\)/layout.tsx
git -C /Users/Hemant/Desktop/projects/relivo/relivo-fe-server commit -m "feat: add centered (auth) route group layout"
```

---

## Task 5: Create sign-in page

**Files:**
- Create: `src/app/(auth)/sign-in/[[...sign-in]]/page.tsx`

`[[...sign-in]]` is Clerk's catch-all segment — Clerk uses sub-paths under `/sign-in` for its internal flows (factor verification, SSO callbacks, etc.). The page is a server component: it checks for an existing session and redirects to `/app` immediately if one exists (prevents back-button access for already-signed-in users).

- [ ] **Step 1: Create `src/app/(auth)/sign-in/[[...sign-in]]/page.tsx`**

```tsx
import { auth } from "@clerk/nextjs/server";
import { redirect } from "next/navigation";
import { SignIn } from "@clerk/nextjs";

export default async function SignInPage() {
  const { userId } = await auth();
  if (userId) redirect("/app");
  return <SignIn />;
}
```

- [ ] **Step 2: Verify the sign-in page renders**

```bash
npm run dev
```

Visit `http://localhost:3001/sign-in` — Clerk's prebuilt sign-in widget should appear centered on a white background. Confirm:
- The widget renders (requires real `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` in `.env.local`)
- The primary button color is dark gray (gray-900 = `#111827`)
- Page has no Navbar or Footer

- [ ] **Step 3: Verify redirect guard**

Sign in with a test account, then manually navigate to `http://localhost:3001/sign-in` — should immediately redirect to `/app`.

- [ ] **Step 4: Commit**

```bash
git -C /Users/Hemant/Desktop/projects/relivo/relivo-fe-server add "src/app/(auth)/sign-in"
git -C /Users/Hemant/Desktop/projects/relivo/relivo-fe-server commit -m "feat: add Clerk sign-in page with session redirect guard"
```

---

## Task 6: Create sign-up page

**Files:**
- Create: `src/app/(auth)/sign-up/[[...sign-up]]/page.tsx`

Same pattern as sign-in. After successful sign-up, `NEXT_PUBLIC_CLERK_AFTER_SIGN_UP_URL=/onboarding` (set in `.env.local`) tells Clerk where to redirect.

- [ ] **Step 1: Create `src/app/(auth)/sign-up/[[...sign-up]]/page.tsx`**

```tsx
import { auth } from "@clerk/nextjs/server";
import { redirect } from "next/navigation";
import { SignUp } from "@clerk/nextjs";

export default async function SignUpPage() {
  const { userId } = await auth();
  if (userId) redirect("/app");
  return <SignUp />;
}
```

- [ ] **Step 2: Verify the sign-up page renders**

Visit `http://localhost:3001/sign-up` — Clerk's prebuilt sign-up widget should appear. Confirm:
- Widget renders with gray-900 primary color
- No Navbar or Footer visible

- [ ] **Step 3: Commit**

```bash
git -C /Users/Hemant/Desktop/projects/relivo/relivo-fe-server add "src/app/(auth)/sign-up"
git -C /Users/Hemant/Desktop/projects/relivo/relivo-fe-server commit -m "feat: add Clerk sign-up page with session redirect guard"
```

---

## Task 7: Create legacy redirect pages

**Files:**
- Create: `src/app/(public)/login/page.tsx`
- Create: `src/app/(public)/signup/page.tsx`

Old links (e.g. in external content, emails, or cached pages) that point to `/login` and `/signup` should not 404. These server components call `redirect()` immediately — no UI renders.

- [ ] **Step 1: Create `src/app/(public)/login/page.tsx`**

```tsx
import { redirect } from "next/navigation";

export default function LoginRedirect() {
  redirect("/sign-in");
}
```

- [ ] **Step 2: Create `src/app/(public)/signup/page.tsx`**

```tsx
import { redirect } from "next/navigation";

export default function SignupRedirect() {
  redirect("/sign-up");
}
```

- [ ] **Step 3: Verify redirects**

Visit `http://localhost:3001/login` — should redirect to `/sign-in`.
Visit `http://localhost:3001/signup` — should redirect to `/sign-up`.

- [ ] **Step 4: Commit**

```bash
git -C /Users/Hemant/Desktop/projects/relivo/relivo-fe-server add "src/app/(public)/login/page.tsx" "src/app/(public)/signup/page.tsx"
git -C /Users/Hemant/Desktop/projects/relivo/relivo-fe-server commit -m "feat: add legacy redirects /login → /sign-in and /signup → /sign-up"
```

---

## Task 8: Create onboarding page

**Files:**
- Create: `src/app/onboarding/page.tsx`

This is a standalone route — no sidebar, no header. Protected by middleware (unauthenticated users are redirected to `/sign-in`). Minimal stub: centered welcome card with a "Go to App" button.

- [ ] **Step 1: Create `src/app/onboarding/page.tsx`**

```tsx
import Link from "next/link";

export default function OnboardingPage() {
  return (
    <div className="flex min-h-dvh items-center justify-center bg-white">
      <div className="flex max-w-sm flex-col items-center gap-6 rounded-2xl border border-gray-100 bg-white p-10 text-center shadow-sm">
        <div className="flex flex-col gap-2">
          <h1 className="font-sans text-2xl font-bold text-gray-900">
            Welcome to Relivo
          </h1>
          <p className="text-sm text-gray-500">
            Your account is ready. Head to the app to get started.
          </p>
        </div>
        <Link
          href="/app"
          className="w-full rounded-lg bg-gray-900 px-6 py-2.5 text-center text-sm font-semibold text-white transition-colors hover:bg-gray-700"
        >
          Go to App
        </Link>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify the page renders**

Visit `http://localhost:3001/onboarding` — should show the centered welcome card.

Verify protection: sign out of Clerk, then navigate to `http://localhost:3001/onboarding` — middleware should redirect to `/sign-in`.

- [ ] **Step 3: Commit**

```bash
git -C /Users/Hemant/Desktop/projects/relivo/relivo-fe-server add src/app/onboarding/page.tsx
git -C /Users/Hemant/Desktop/projects/relivo/relivo-fe-server commit -m "feat: add onboarding stub page (protected, post-signup)"
```

---

## Task 9: Update Navbar to be auth-aware

**Files:**
- Modify: `src/app/(public)/_components/Navbar.tsx`

The Navbar is already a `"use client"` component. We import `useAuth` from `@clerk/nextjs` and conditionally render auth CTAs. When `isSignedIn` is true: show "Go to App" link + `<UserButton />`; when false: show the existing Login/Get Started buttons (with updated hrefs pointing to `/sign-in` and `/sign-up`).

- [ ] **Step 1: Replace `src/app/(public)/_components/Navbar.tsx` with this content**

```tsx
"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { Menu, X } from "lucide-react";
import { useAuth, UserButton } from "@clerk/nextjs";
import { cn } from "@/lib/utils";

const navLinks = [
  { href: "/about", label: "About" },
  { href: "/pricing", label: "Pricing" },
  { href: "/docs", label: "Docs" },
  { href: "/blog", label: "Blog" },
];

export function Navbar() {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();
  const { isSignedIn } = useAuth();

  return (
    <header className="fixed top-0 left-0 right-0 z-50 border-b border-gray-200 bg-white/90 backdrop-blur-md">
      <nav className="mx-auto flex max-w-7xl items-center justify-between px-6 py-4">
        {/* Logo */}
        <Link href="/" className="flex items-center gap-2.5 cursor-pointer">
          <Image src="/logo.svg" alt="Relivo" width={28} height={28} className="shrink-0" />
          <span className="font-mono text-base font-bold text-gray-900 tracking-tight">
            relivo
          </span>
        </Link>

        {/* Desktop nav */}
        <div className="hidden items-center gap-7 md:flex">
          {navLinks.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className={cn(
                "text-sm font-medium transition-colors duration-200 cursor-pointer",
                pathname === link.href
                  ? "text-gray-900"
                  : "text-gray-500 hover:text-gray-900"
              )}
            >
              {link.label}
            </Link>
          ))}
        </div>

        {/* Desktop CTA */}
        <div className="hidden items-center gap-3 md:flex">
          {isSignedIn ? (
            <>
              <Link
                href="/app"
                className="text-sm font-medium text-gray-500 hover:text-gray-900 transition-colors duration-200 cursor-pointer"
              >
                Go to App
              </Link>
              <UserButton afterSignOutUrl="/sign-in" />
            </>
          ) : (
            <>
              <Link
                href="/sign-in"
                className="text-sm font-medium text-gray-500 hover:text-gray-900 transition-colors duration-200 cursor-pointer"
              >
                Login
              </Link>
              <Link
                href="/sign-up"
                className="rounded-lg bg-gray-900 px-4 py-2 text-sm font-semibold text-white hover:bg-gray-700 transition-colors duration-200 cursor-pointer"
              >
                Get Started
              </Link>
            </>
          )}
        </div>

        {/* Mobile toggle */}
        <button
          onClick={() => setOpen(!open)}
          className="text-gray-500 hover:text-gray-900 transition-colors cursor-pointer md:hidden"
          aria-label="Toggle menu"
        >
          {open ? <X size={20} /> : <Menu size={20} />}
        </button>
      </nav>

      {/* Mobile menu */}
      {open && (
        <div className="border-t border-gray-200 bg-white px-6 py-5 md:hidden">
          <div className="flex flex-col gap-4">
            {navLinks.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                onClick={() => setOpen(false)}
                className="text-sm font-medium text-gray-600 hover:text-gray-900 transition-colors cursor-pointer"
              >
                {link.label}
              </Link>
            ))}
            <div className="flex flex-col gap-3 border-t border-gray-100 pt-4">
              {isSignedIn ? (
                <>
                  <Link
                    href="/app"
                    onClick={() => setOpen(false)}
                    className="text-sm font-medium text-gray-500 hover:text-gray-900 transition-colors cursor-pointer"
                  >
                    Go to App
                  </Link>
                  <div className="flex items-center">
                    <UserButton afterSignOutUrl="/sign-in" />
                  </div>
                </>
              ) : (
                <>
                  <Link
                    href="/sign-in"
                    onClick={() => setOpen(false)}
                    className="text-sm font-medium text-gray-500 hover:text-gray-900 transition-colors cursor-pointer"
                  >
                    Login
                  </Link>
                  <Link
                    href="/sign-up"
                    onClick={() => setOpen(false)}
                    className="rounded-lg bg-gray-900 px-4 py-2.5 text-center text-sm font-semibold text-white hover:bg-gray-700 transition-colors cursor-pointer"
                  >
                    Get Started
                  </Link>
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </header>
  );
}
```

- [ ] **Step 2: Verify signed-out state**

Visit `http://localhost:3001` while signed out — Navbar should show "Login" and "Get Started" buttons. "Login" → `/sign-in`, "Get Started" → `/sign-up`.

- [ ] **Step 3: Verify signed-in state**

Sign in via `/sign-in`, then navigate to `http://localhost:3001` (or any public page) — Navbar should show "Go to App" link and the Clerk `UserButton` avatar. Clicking the avatar opens Clerk's profile/sign-out popover.

- [ ] **Step 4: Commit**

```bash
git -C /Users/Hemant/Desktop/projects/relivo/relivo-fe-server add "src/app/(public)/_components/Navbar.tsx"
git -C /Users/Hemant/Desktop/projects/relivo/relivo-fe-server commit -m "feat: make Navbar auth-aware with Clerk UserButton"
```

---

## Task 10: Add UserButton to app header

**Files:**
- Modify: `src/app/app/_components/header/MainHeader.tsx`

`<UserButton />` is a Clerk client component. `MainHeader` currently has no `"use client"` directive. We add it and render `<UserButton />` in the right-side actions row alongside the existing Bell and Help buttons.

- [ ] **Step 1: Replace `src/app/app/_components/header/MainHeader.tsx` with this content**

```tsx
"use client";

import { Bell, ChevronDown, HelpCircle } from "lucide-react";
import { UserButton } from "@clerk/nextjs";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

export function MainHeader() {
  return (
    <TooltipProvider>
      <header className="flex shrink-0 items-center justify-between bg-white px-4 py-4 dark:border-zinc-800 dark:bg-zinc-950">
        {/* Model selector */}
        <button className="flex cursor-pointer items-center gap-1.5 rounded-md px-2 py-1 text-sm font-semibold text-zinc-900 transition-colors hover:bg-zinc-100 dark:text-zinc-100 dark:hover:bg-zinc-800">
          Relivo
          <ChevronDown className="size-4" />
        </button>

        {/* Right actions */}
        <div className="flex items-center gap-0.5">
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                className="cursor-pointer rounded-md p-1.5 text-zinc-900 transition-colors hover:bg-zinc-100 dark:text-zinc-100 dark:hover:bg-zinc-800"
                aria-label="Help"
              >
                <HelpCircle className="size-4" />
              </button>
            </TooltipTrigger>
            <TooltipContent>Help</TooltipContent>
          </Tooltip>

          <Tooltip>
            <TooltipTrigger asChild>
              <button
                className="relative cursor-pointer rounded-md p-1.5 text-zinc-900 transition-colors hover:bg-zinc-100 dark:text-zinc-100 dark:hover:bg-zinc-800"
                aria-label="Notifications"
              >
                <Bell className="size-4" />
                {/* Notification dot */}
                <span className="absolute right-1.5 top-1.5 size-1.5 rounded-full bg-violet-500" />
              </button>
            </TooltipTrigger>
            <TooltipContent>Notifications</TooltipContent>
          </Tooltip>

          <div className="ml-1">
            <UserButton afterSignOutUrl="/sign-in" />
          </div>
        </div>
      </header>
    </TooltipProvider>
  );
}
```

- [ ] **Step 2: Verify UserButton renders in the app**

Visit `http://localhost:3001/app` (signed in) — the header should show the Clerk user avatar to the right of the Bell and Help icons. Clicking it opens Clerk's native profile/sign-out popover.

- [ ] **Step 3: Verify sign-out flow**

In the app header, click the UserButton → select "Sign out". Clerk should sign the user out and redirect to `/sign-in` (via `afterSignOutUrl`).

- [ ] **Step 4: Commit**

```bash
git -C /Users/Hemant/Desktop/projects/relivo/relivo-fe-server add src/app/app/_components/header/MainHeader.tsx
git -C /Users/Hemant/Desktop/projects/relivo/relivo-fe-server commit -m "feat: add Clerk UserButton to app header"
```

---

## Task 11: End-to-end verification

No code changes — this task verifies all flows work together.

- [ ] **Step 1: Full sign-up flow**

1. Visit `http://localhost:3001/sign-up`
2. Create a new account
3. After success → should land on `/onboarding`
4. Click "Go to App" → should land on `/app`

- [ ] **Step 2: Full sign-in flow**

1. Sign out (via UserButton in header)
2. Visit `http://localhost:3001/sign-in`
3. Sign in with existing credentials
4. After success → should land on `/app`

- [ ] **Step 3: Protected route enforcement**

1. Sign out completely
2. Navigate to `http://localhost:3001/app` → should redirect to `/sign-in`
3. Navigate to `http://localhost:3001/onboarding` → should redirect to `/sign-in`

- [ ] **Step 4: Legacy redirect verification**

1. Visit `http://localhost:3001/login` → should redirect to `/sign-in`
2. Visit `http://localhost:3001/signup` → should redirect to `/sign-up`

- [ ] **Step 5: Navbar auth-awareness**

1. While signed in, visit `http://localhost:3001` → Navbar shows "Go to App" + avatar
2. Sign out → Navbar shows "Login" + "Get Started"

- [ ] **Step 6: Already-signed-in guard**

While signed in, navigate directly to `/sign-in` → should redirect to `/app` (not show the sign-in widget).

- [ ] **Step 7: Toast verification**

Open browser console at any route — confirm no Toaster-related errors. The `<Toaster />` is present in the DOM (visible in dev tools). No visible toast is expected at rest — toasts will fire from future features.
