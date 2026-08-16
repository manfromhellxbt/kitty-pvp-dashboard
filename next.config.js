/** @type {import('next').NextConfig} */
const nextConfig = {
  // ISR handled at the page-level via revalidate
  trailingSlash: true,
};

module.exports = nextConfig;
