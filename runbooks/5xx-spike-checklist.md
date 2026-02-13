# 5xx Spike Checklist

## Symptoms
- Elevated 5xx error rate
- Increased latency p95
- Top failing endpoint(s)

## Checks
1. Check recent deploys (last 30–60 minutes)
2. Check dependency health (DB, cache, downstream APIs)
3. Inspect top failing route(s) and error codes
4. Verify feature flags / configuration changes

## Mitigations
- Roll back last deploy if correlated
- Scale service / increase connection pool cautiously
- Apply rate limits to noisy clients if needed