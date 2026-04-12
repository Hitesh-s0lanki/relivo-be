# Clerk Auth Integration — relivo-fe-server

**Date:** 2026-04-12  
**Status:** Approved  
**Scope:** Login, signup, protected routes, auth-aware Navbar, onboarding stub

---

## Overview

Add Clerk authentication to `relivo-fe-server` (Next.js 16, App Router). Use Clerk's prebuilt `<SignIn />` and `<SignUp />` components with minimal appearance customization (gray-900 primary color). Protect `/app` and `/onboarding` via Clerk middleware. Make the public Navbar auth-aware. Add `<UserButton />` to the app header.

---

## Route Structure

```
src/app/
├── (auth)/                            ← new: clean centered layout
│   ├── layout.tsx                     ← flex center, full-height, white bg
│   ├── sign-in/
│   │   └── [[...sign-in]]/
│   │       └── page.tsx               ← server: redirect if signed in → /app
│   └── sign-up/
│       └── [[...sign-up]]/
│           └── page.tsx               ← server: redirect if signed in → /app
├── (public)/
│   ├── _components/
│   │   └── Navbar.tsx                 ← updated: auth-aware
│   ├── login/
│   │   └── page.tsx                   ← redirect('/sign-in')
│   └── signup/
│       └── page.tsx                   ← redirect('/sign-up')
├── app/                               ← existing dashboard, unchanged
│   └── _components/
│       └── header/
│           └── MainHeader.tsx         ← add <UserButton />
├── onboarding/
│   └── page.tsx                       ← protected standalone page, no sidebar
└── layout.tsx                         ← add ClerkProvider + Toaster
```

**URL mappings:**
- `/sign-in` → Clerk SignIn widget, after sign-in → `/app`
- `/sign-up` → Clerk SignUp widget, after sign-up → `/onboarding`
- `/onboarding` → protected post-signup page (no sidebar)
- `/login` → permanent redirect to `/sign-in`
- `/signup` → permanent redirect to `/sign-up`

---

## Middleware

**`src/middleware.ts`**

```ts
import { clerkMiddleware, createRouteMatcher } from '@clerk/nextjs/server'

const isProtectedRoute = createRouteMatcher(['/app(.*)', '/onboarding(.*)'])

export default clerkMiddleware(async (auth, req) => {
  if (isProtectedRoute(req)) await auth.protect()
})

export const config = {
  matcher: [
    '/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)',
    '/(api|trpc)(.*)',
  ],
}
```

- `/app(.*)` and `/onboarding(.*)` are protected — unauthenticated requests redirect to `/sign-in`
- All other routes are public

---

## ClerkProvider + Toaster (Root Layout)

**`src/app/layout.tsx`**

Wrap the root layout body with `ClerkProvider`. Add Sonner `<Toaster />` here so it is available on every route including auth pages.

```tsx
import { ClerkProvider } from '@clerk/nextjs'
import { Toaster } from 'sonner'

<ClerkProvider
  afterSignOutUrl="/sign-in"
  appearance={{ variables: { colorPrimary: '#111827' } }}
>
  <html lang="en" className={`${fonts} h-full antialiased`}>
    <body className="min-h-full flex flex-col">
      {children}
      <Toaster richColors position="bottom-right" visibleToasts={3} />
    </body>
  </html>
</ClerkProvider>
```

---

## Auth Layout

**`src/app/(auth)/layout.tsx`**

No Navbar, no Footer — just a centered container. Auth pages are the only content.

```tsx
export default function AuthLayout({ children }) {
  return (
    <div className="flex min-h-dvh items-center justify-center bg-white">
      {children}
    </div>
  )
}
```

---

## Auth Pages

### Sign-In — `src/app/(auth)/sign-in/[[...sign-in]]/page.tsx`

Server component. Checks `auth()` — if a session exists, redirect immediately to `/app` (prevents back-button access for logged-in users). Otherwise renders the Clerk `<SignIn />` widget.

```tsx
import { auth } from '@clerk/nextjs/server'
import { redirect } from 'next/navigation'
import { SignIn } from '@clerk/nextjs'

export default async function SignInPage() {
  const { userId } = await auth()
  if (userId) redirect('/app')
  return <SignIn />
}
```

### Sign-Up — `src/app/(auth)/sign-up/[[...sign-up]]/page.tsx`

Same pattern. After successful sign-up, Clerk redirects to `/onboarding` (via `NEXT_PUBLIC_CLERK_AFTER_SIGN_UP_URL`).

### Legacy Redirects

`(public)/login/page.tsx` and `(public)/signup/page.tsx` — call `redirect('/sign-in')` and `redirect('/sign-up')` respectively so existing links don't 404.

---

## Onboarding Page

**`src/app/onboarding/page.tsx`**

Standalone route (no sidebar/header), protected by middleware. Minimal placeholder — a centered card with a welcome message and a "Go to App" button for now.

---

## Auth-Aware Navbar

**`src/app/(public)/_components/Navbar.tsx`**

Import `useAuth` from `@clerk/nextjs`. In the signed-in state, replace the Login/Get Started buttons with:
- "Go to App" link → `/app`  
- `<UserButton afterSignOutUrl="/sign-in" />` (Clerk's built-in avatar + popover)

In signed-out state, update hrefs: `/login` → `/sign-in`, `/signup` → `/sign-up`.

Same conditional logic in the mobile menu.

---

## App Header UserButton

**`src/app/app/_components/header/MainHeader.tsx`**

Add `<UserButton afterSignOutUrl="/sign-in" />` to the right-side actions row alongside the existing Bell and Help icon buttons. Clerk's UserButton renders the user avatar and provides a built-in popover for profile management and sign-out — no custom component needed.

---

## Environment Variables

**`.env.local`** (create at project root, never commit):

```
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_test_...
CLERK_SECRET_KEY=sk_test_...
NEXT_PUBLIC_CLERK_SIGN_IN_URL=/sign-in
NEXT_PUBLIC_CLERK_SIGN_UP_URL=/sign-up
NEXT_PUBLIC_CLERK_AFTER_SIGN_IN_URL=/app
NEXT_PUBLIC_CLERK_AFTER_SIGN_UP_URL=/onboarding
```

Obtain keys from the Clerk dashboard after creating an application.

---

## Package to Install

```
@clerk/nextjs   (latest — v6.x at time of writing)
```

No other dependencies needed — Sonner is already installed at v2.0.7.

---

## What Is Not In Scope

- Custom auth form UI (Clerk prebuilt components used as-is)
- Organization-level auth or multi-tenancy
- Onboarding flow implementation (page is a stub)
- Social OAuth provider configuration (done in Clerk dashboard)
- Error toast on auth failure (Clerk handles error display natively within the widget)
