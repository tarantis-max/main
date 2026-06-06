function fmtDate(val) {
  if (!val) return '—';
  return new Date(val).toLocaleDateString('en-US', { timeZone: 'UTC' });
}

function Row({ label, value }) {
  return (
    <div className="flex py-2.5 border-b border-gray-100 last:border-0">
      <dt className="w-48 text-sm text-gray-500 shrink-0">{label}</dt>
      <dd className="text-sm text-gray-900">{value || '—'}</dd>
    </div>
  );
}

const GENDER_MAP    = { M: 'Male', F: 'Female', N: 'Non-binary / Not specified' };
const CITIZEN_MAP   = { Y: 'US Citizen', N: 'Non-US', R: 'Permanent Resident' };

export default function ProfileTab({ student }) {
  return (
    <div className="card p-5 max-w-2xl">
      <dl>
        <Row label="Student ID"    value={student.PEOPLE_CODE_ID} />
        <Row label="Last Name"     value={student.last_name} />
        <Row label="First Name"    value={student.first_name} />
        <Row label="Middle Name"   value={student.middle_name} />
        <Row label="Preferred Name" value={student.preferred_name} />
        <Row label="Date of Birth" value={fmtDate(student.BIRTH_DATE)} />
        <Row label="Gender"        value={GENDER_MAP[student.gender] ?? student.gender} />
        <Row label="Ethnicity"     value={student.ethnicity} />
        <Row label="Citizenship"   value={CITIZEN_MAP[student.citizen_code] ?? student.citizen_code} />
        <Row label="Marital Status" value={student.marital_status} />
        <Row label="Veteran Status" value={student.veteran_status} />
        <Row label="Disability"    value={student.disability_status} />
      </dl>
    </div>
  );
}
