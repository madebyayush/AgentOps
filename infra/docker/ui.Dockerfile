# --- BUILD STAGE ---
FROM node:20-alpine AS build
WORKDIR /app

# Copy root configurations and workspace locks
COPY package*.json ./
COPY turbo.json ./
COPY apps/ui/package*.json ./apps/ui/
COPY packages/shared-types/package*.json ./packages/shared-types/

# Install workspaces dependencies
RUN npm ci --include=dev

# Copy source trees
COPY apps/ui/ ./apps/ui/
COPY packages/shared-types/ ./packages/shared-types/

# Execute Turborepo build task for ui
RUN npm run build --workspace=@agentops/ui

# --- PRODUCTION DEPLOYMENT STAGE ---
FROM nginx:stable-alpine AS runner
COPY --from=build /app/apps/ui/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
