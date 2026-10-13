param([string]$Root = (Split-Path -Parent $PSScriptRoot))
$ErrorActionPreference = 'Stop'
$resolvedRoot = (Resolve-Path -LiteralPath $Root).Path
$issues = [System.Collections.Generic.List[string]]::new()
function Check([bool]$Condition, [string]$Message) { if (-not $Condition) { $issues.Add($Message) } }
$fixture = Get-Content -LiteralPath (Join-Path $resolvedRoot 'data/fixtures.json') -Raw -Encoding utf8 | ConvertFrom-Json
$policy = Get-Content -LiteralPath (Join-Path $resolvedRoot 'data/policy.json') -Raw -Encoding utf8 | ConvertFrom-Json
$scenarios = @(Get-Content -LiteralPath (Join-Path $resolvedRoot 'evals/scenarios.jsonl') -Encoding utf8 | Where-Object { $_.Trim() } | ForEach-Object { $_ | ConvertFrom-Json })
Check ($scenarios.Count -eq 36) 'Expected 36 scenario specifications'
Check (@($scenarios.case_id | Select-Object -Unique).Count -eq $scenarios.Count) 'Duplicate scenario IDs'
Check (@($fixture.orders.id | Select-Object -Unique).Count -eq $fixture.orders.Count) 'Duplicate order IDs'
Check (@($fixture.users.id | Select-Object -Unique).Count -eq $fixture.users.Count) 'Duplicate user IDs'
Check ($fixture.simulated -and $policy.simulated) 'Simulation flag missing'
$orderIds = @($fixture.orders.id)
$userIds = @($fixture.users.id)
$policyIds = @($policy.policies.id)
$clauseIds = @($policy.policies | ForEach-Object { $_.clauses.chunk_id })
foreach ($o in $fixture.orders) {
  Check ($o.paid_amount_fen -ge 0 -and $o.refunded_amount_fen -ge 0 -and $o.refunded_amount_fen -le $o.paid_amount_fen) "Invalid amount for $($o.id)"
  Check ($userIds -contains $o.customer_id) "Unknown customer for $($o.id)"
  $u = @($fixture.users | Where-Object { $_.id -eq $o.customer_id })[0]
  Check ($u.tenant_id -eq $o.tenant_id) "Order/customer tenant mismatch for $($o.id)"
}
foreach ($s in $scenarios) {
  Check ($userIds -contains $s.actor) "Unknown actor in $($s.case_id)"
  Check ($s.fixture_version -eq $fixture.fixture_version) "Fixture version mismatch in $($s.case_id)"
  Check ($policyIds -contains $s.policy_version) "Unknown policy in $($s.case_id)"
  Check (@('domain','api','agent') -contains $s.level) "Invalid scenario level in $($s.case_id)"
  Check ($null -ne $s.expected) "Missing oracle in $($s.case_id)"
  if ($s.input.order_id) { Check ($orderIds -contains $s.input.order_id) "Unknown order in $($s.case_id)" }
  foreach ($ref in @($s.expected.citations_include) + @($s.expected.citations_exclude)) {
    if ($ref) { Check ($clauseIds -contains $ref) "Unknown clause $ref in $($s.case_id)" }
  }
  foreach ($step in @($s.setup_steps)) { if ($step.order_id) { Check ($orderIds -contains $step.order_id) "Unknown setup order in $($s.case_id)" } }
  foreach ($override in @($s.order_overrides)) { if ($override.id) { Check ($orderIds -contains $override.id) "Unknown override order in $($s.case_id)" } }
}
$markdownFiles = @(
  Get-ChildItem -LiteralPath $resolvedRoot -File -Filter '*.md'
  foreach ($folder in @('docs','data','evals')) {
    Get-ChildItem -LiteralPath (Join-Path $resolvedRoot $folder) -Recurse -File -Filter '*.md'
  }
)
foreach ($f in $markdownFiles) {
  $content = Get-Content -LiteralPath $f.FullName -Raw -Encoding utf8
  foreach ($m in [regex]::Matches($content, '\[[^\]]+\]\(([^\)]+)\)')) {
    $target = $m.Groups[1].Value
    if ($target -match '^(https?://|#)' -or $target -match '^[A-Za-z]:') { continue }
    $target = ($target -split '#')[0]
    if ($target) { Check (Test-Path -LiteralPath (Join-Path $f.DirectoryName $target)) "Broken link in $($f.Name): $target" }
  }
}
$report = [ordered]@{
  checked_at_utc = [DateTime]::UtcNow.ToString('o')
  result = if ($issues.Count -eq 0) { 'PASS' } else { 'FAIL' }
  root = $resolvedRoot
  scope = 'Documentation links and fixture/scenario structure only; no application or Agent behavior tested.'
  markdown_count = $markdownFiles.Count
  orders = $fixture.orders.Count
  scenarios = $scenarios.Count
  issues = @($issues)
}
$report | ConvertTo-Json -Depth 6
if ($issues.Count -gt 0) { exit 1 }
