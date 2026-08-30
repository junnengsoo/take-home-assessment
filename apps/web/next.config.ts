import type { NextConfig } from "next";

function configuredOrigin(value: string | undefined) {
  if (!value) {
    return null;
  }
  try {
    return new URL(value).origin;
  } catch {
    return null;
  }
}

const nextConfig: NextConfig = {
  reactStrictMode: true,
  async headers() {
    const connectSources = [
      "'self'",
      "http://localhost:*",
      "http://127.0.0.1:*",
      configuredOrigin(process.env.NEXT_PUBLIC_API_URL),
      configuredOrigin(process.env.NEXT_PUBLIC_SUPABASE_URL)
    ].filter(Boolean);
    const contentSecurityPolicy = [
      "default-src 'self'",
      "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://challenges.cloudflare.com",
      "style-src 'self' 'unsafe-inline'",
      "img-src 'self' data:",
      "font-src 'self'",
      `connect-src ${connectSources.join(" ")}`,
      "frame-src https://challenges.cloudflare.com",
      "base-uri 'self'",
      "form-action 'self'",
      "frame-ancestors 'none'"
    ].join("; ");

    return [
      {
        source: "/(.*)",
        headers: [
          {
            key: "Content-Security-Policy",
            value: contentSecurityPolicy
          }
        ]
      }
    ];
  }
};

export default nextConfig;
