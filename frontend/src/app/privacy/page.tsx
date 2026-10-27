import type { Metadata } from "next";
import LegalPage from "@/components/LegalPage";

export const metadata: Metadata = {
  title: "Privacy Policy · SET>READY",
  description: "How SET>READY collects, uses, shares, and protects information.",
};

export default function PrivacyPage() {
  return (
    <LegalPage title="Privacy Policy" updated="June 11, 2026">
      <p>
        This Privacy Policy explains how SET&gt;READY (&ldquo;SET&gt;READY,&rdquo; &ldquo;we,&rdquo; &ldquo;us,&rdquo;
        or &ldquo;our&rdquo;), operated by [Legal Entity Name], collects, uses, shares, and protects
        information when you use our production-management application and related services (the
        &ldquo;Service&rdquo;). By using the Service, you agree to the practices described here.
      </p>

      <h2>1. Information we collect</h2>
      <h3>Information you provide</h3>
      <ul>
        <li><strong>Account information:</strong> your name, email address, optional production company name, and a password (handled by our authentication provider).</li>
        <li><strong>Production content:</strong> project details, schedules, shoot locations and addresses, and notes you enter.</li>
        <li>
          <strong>Information about your crew, talent, and contacts:</strong> names, email addresses,
          phone numbers, roles, departments, and call times that you choose to add so that the Service
          can build and deliver call sheets.
        </li>
      </ul>
      <h3>Information collected automatically</h3>
      <ul>
        <li><strong>Technical and log data:</strong> IP address, request metadata, and error logs, used to operate, secure, and rate-limit the Service.</li>
        <li><strong>Cookies:</strong> a session cookie that keeps you signed in. We do not use advertising or third-party tracking cookies.</li>
      </ul>

      <h2>2. Information about your crew, talent, and contacts</h2>
      <p>
        When you add another person&rsquo;s contact information, you direct us to process it on your behalf
        for the sole purpose of providing the Service to you &mdash; for example, generating a call sheet and
        emailing each person their call time and a confirmation link.
      </p>
      <ul>
        <li>You are responsible for ensuring you have the right to share that information with us and to contact those individuals.</li>
        <li>We act as a <strong>service provider</strong> (processor) for that information. We do not sell it and do not use it for our own independent purposes.</li>
        <li>If one of your crew or contacts asks us about their information, we will generally direct them to you, and we will assist you in responding.</li>
      </ul>

      <h2>3. How we use information</h2>
      <ul>
        <li>To provide, operate, and maintain the Service;</li>
        <li>To generate call sheets and send emails on your behalf;</li>
        <li>To secure the Service, prevent abuse, and enforce our terms;</li>
        <li>To communicate with you about your account and support requests;</li>
        <li>To comply with legal obligations.</li>
      </ul>

      <h2>4. How we share information</h2>
      <p>
        We do not sell personal information. We share information only with service providers
        (&ldquo;subprocessors&rdquo;) that help us run the Service, and only as needed for them to perform
        their function:
      </p>
      <ul>
        <li><strong>Supabase</strong> &mdash; authentication and database hosting;</li>
        <li><strong>Anthropic</strong> &mdash; AI processing used to generate call sheets from your project data;</li>
        <li><strong>SendGrid</strong> &mdash; email delivery;</li>
        <li><strong>Vercel</strong> and <strong>Railway</strong> &mdash; application hosting;</li>
        <li><strong>OpenStreetMap</strong> and <strong>Open-Meteo</strong> &mdash; map, geocoding, and weather lookups for the address you enter.</li>
      </ul>
      <p>
        We do not permit our providers to use your data to train their models. We may also disclose
        information if required by law or to protect our rights, users, or the public.
      </p>

      <h2>5. Data retention and deletion</h2>
      <p>
        We retain your information while your account is active. You can delete a project at any time,
        which removes its associated crew, talent, contacts, schedule, and call sheets. You may request
        deletion of your account and associated data by contacting us; residual copies may persist in
        backups for a limited period before being overwritten.
      </p>

      <h2>6. Security</h2>
      <p>
        We protect information using encryption in transit (HTTPS), access controls, database row-level
        security, and rate limiting on public endpoints. No method of transmission or storage is
        completely secure, and we cannot guarantee absolute security.
      </p>

      <h2>7. Your rights and choices</h2>
      <p>
        Depending on where you live, you may have rights to access, correct, delete, or port your personal
        information, and to object to or restrict certain processing. To exercise these rights, contact us
        at support@set-ready-set.com. We will not discriminate against you for exercising your rights. For information
        about crew or contacts that a producer added, requests are generally directed to that producer.
      </p>
      <h3>California residents</h3>
      <p>
        We do not &ldquo;sell&rdquo; or &ldquo;share&rdquo; personal information as those terms are defined under
        the California Consumer Privacy Act (CCPA/CPRA). You may exercise your CCPA rights by contacting us
        at the email address in Section 10.
      </p>

      <h2>8. Children</h2>
      <p>
        The Service is not directed to children under 16, and we do not knowingly collect their personal
        information.
      </p>

      <h2>9. Changes to this policy</h2>
      <p>
        We may update this Privacy Policy from time to time. We will revise the &ldquo;Last updated&rdquo; date
        above and, where appropriate, notify you of material changes.
      </p>

      <h2>10. Contact us</h2>
      <p>
        Questions about this Policy or your information? Contact us at support@set-ready-set.com.
      </p>
    </LegalPage>
  );
}
