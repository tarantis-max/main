const DML = /\b(INSERT|UPDATE|DELETE|DROP|TRUNCATE|EXEC|EXECUTE|ALTER|CREATE|MERGE|GRANT|REVOKE|DENY|BULK\s+INSERT|OPENROWSET|OPENDATASOURCE|XP_)\b/i;

function validateSelect(rawSql) {
  // Strip comments before checking
  const stripped = rawSql
    .replace(/--[^\n]*/g, '')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .trim();

  if (!/^SELECT\b/i.test(stripped)) {
    const err = new Error('Only SELECT statements are permitted.');
    err.status = 400;
    throw err;
  }

  if (DML.test(stripped)) {
    const err = new Error('Query contains a disallowed keyword.');
    err.status = 400;
    throw err;
  }

  // No semicolons — prevents statement chaining even on a read-only DB
  if (stripped.includes(';')) {
    const err = new Error('Multi-statement queries are not permitted.');
    err.status = 400;
    throw err;
  }

  // Inject TOP cap if the query doesn't already limit rows
  if (!/\bTOP\s+\d+\b/i.test(stripped) && !/FETCH\s+NEXT\s+\d+/i.test(stripped)) {
    return stripped.replace(/^(\s*SELECT\s+)/i, '$1TOP 500 ');
  }

  return stripped;
}

module.exports = { validateSelect };
