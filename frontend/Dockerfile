# The frontend as a Railway service (the own-copy template, docs/own-copy-plan.md).
# Production stays on Vercel; this is for a producer's own copy, where both
# services run in one Railway project.
#
# Next.js bakes every NEXT_PUBLIC_* value into the bundle at BUILD time, so
# they arrive as build args, not runtime env. Railway passes a service's
# variables as build args to any ARG a Dockerfile declares, so the three below
# only need to exist on the service.

FROM node:22-alpine AS build
WORKDIR /app

ARG NEXT_PUBLIC_SUPABASE_URL
ARG NEXT_PUBLIC_SUPABASE_ANON_KEY
ARG NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_SUPABASE_URL=$NEXT_PUBLIC_SUPABASE_URL \
    NEXT_PUBLIC_SUPABASE_ANON_KEY=$NEXT_PUBLIC_SUPABASE_ANON_KEY \
    NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL \
    NEXT_TELEMETRY_DISABLED=1

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

# next.config.ts sets output: "standalone", so the runtime image is the
# self-contained server plus the static assets, not node_modules.
FROM node:22-alpine
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 HOSTNAME=0.0.0.0

COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY --from=build /app/public ./public

CMD ["sh", "-c", "PORT=${PORT:-3000} node server.js"]
