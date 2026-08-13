import {
  LEGAL_METADATA,
  getLegalDocument,
  hasOperatorMetadata,
  type LegalDocument,
  type LegalOperatorMetadata,
} from './legalDocuments';
import './legal-document.css';

type LegalDocumentPageProps = {
  documentId: LegalDocument['id'];
};

function OperatorMetadataBlock({
  metadata,
}: {
  metadata: LegalOperatorMetadata;
}) {
  if (!hasOperatorMetadata(metadata)) return null;

  const rows: Array<{ label: string; value: string }> = [];
  if (metadata.legalName?.trim()) {
    rows.push({ label: '운영 주체', value: metadata.legalName.trim() });
  }
  if (metadata.representative?.trim()) {
    rows.push({ label: '대표자', value: metadata.representative.trim() });
  }
  if (metadata.address?.trim()) {
    rows.push({ label: '주소', value: metadata.address.trim() });
  }
  if (metadata.privacyOfficer?.trim()) {
    rows.push({
      label: '개인정보 보호책임자',
      value: metadata.privacyOfficer.trim(),
    });
  }
  if (metadata.department?.trim()) {
    rows.push({ label: '담당 부서', value: metadata.department.trim() });
  }
  if (metadata.contactEmail?.trim()) {
    rows.push({ label: '이메일', value: metadata.contactEmail.trim() });
  }
  if (metadata.contactPhone?.trim()) {
    rows.push({ label: '전화', value: metadata.contactPhone.trim() });
  }
  if (rows.length === 0) return null;

  return (
    <section className="legal-document__meta" aria-label="운영 정보">
      <dl>
        {rows.map((row) => (
          <div key={row.label}>
            <dt>{row.label}</dt>
            <dd>{row.value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function HomeBackLink({ className }: { className?: string }) {
  return (
    <a
      className={['legal-document__back', className].filter(Boolean).join(' ')}
      href="/"
      aria-label="동넷으로 돌아가기"
    >
      <span className="legal-document__back-icon" aria-hidden="true">
        ←
      </span>
      <span className="legal-document__back-label">동넷</span>
    </a>
  );
}

/** /terms · /privacy 공개 문서 페이지. 로그인·startup 여부와 무관하게 표시한다. */
export default function LegalDocumentPage({
  documentId,
}: LegalDocumentPageProps) {
  const document = getLegalDocument(documentId);

  return (
    <div className="legal-document">
      <main className="legal-document__main" id="main-content">
        <header className="legal-document__header">
          <HomeBackLink />
          <h1>{document.title}</h1>
          {document.updatedAt ? (
            <p className="legal-document__updated">
              최종 업데이트 {document.updatedAt}
            </p>
          ) : null}
        </header>

        {document.introduction ? (
          <p className="legal-document__intro">{document.introduction}</p>
        ) : null}

        <OperatorMetadataBlock metadata={LEGAL_METADATA} />

        {document.sections.map((section) => (
          <section
            key={section.id}
            className="legal-document__section"
            aria-labelledby={`legal-section-${section.id}`}
          >
            <h2 id={`legal-section-${section.id}`}>{section.heading}</h2>
            {section.paragraphs?.map((paragraph) => (
              <p key={paragraph}>{paragraph}</p>
            ))}
            {section.list && section.list.length > 0 ? (
              <ul>
                {section.list.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            ) : null}
            {section.afterList?.map((paragraph) => (
              <p key={paragraph}>{paragraph}</p>
            ))}
          </section>
        ))}

        <footer className="legal-document__footer">
          <HomeBackLink className="legal-document__back--footer" />
        </footer>
      </main>
    </div>
  );
}
