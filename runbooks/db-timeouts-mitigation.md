# DB Timeouts Mitigation

## Symptoms
- DB timeout errors
- Increased request latency
- Connection pool saturation

## Checks
1. Check DB CPU / connections / locks
2. Check application connection pool limits
3. Identify long-running queries

## Mitigations
- Increase read replicas if safe
- Reduce pool size to prevent DB overload
- Roll back deploy if query plan regression suspected