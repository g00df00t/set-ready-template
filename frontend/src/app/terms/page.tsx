import type { Metadata } from "next";
import LegalPage from "@/components/LegalPage";

export const metadata: Metadata = {
  title: "Terms of Service · SET>READY",
  description: "The terms that govern your use of SET>READY.",
};

export default function TermsPage() {
  return (
    <LegalPage title="Terms of Service" updated="June 11, 2026">
      <p>
        These Terms of Service (&ldquo;Terms&rdquo;) govern your access to and use of the SET&gt;READY
        production-management application and related services (the &ldquo;Service&rdquo;), operated by
        [Legal Entity Name] (&ldquo;SET&gt;READY,&rdquo; &ldquo;we,&rdquo; &ldquo;us,&rdquo; or &ldquo;our&rdquo;).
        By creating an account or using the Service, you agree to these Terms. If you do not agree, do not
        use the Service.
      </p>

      <h2>1. The Service</h2>
      <p>
        SET&gt;READY helps producers organize shoot-day logistics &mdash; crew, schedule, and location &mdash;
        and generate and send call sheets. We may add, change, or remove features over time.
      </p>

      <h2>2. Accounts</h2>
      <ul>
        <li>You must be at least 18 years old and provide accurate account information.</li>
        <li>You are responsible for safeguarding your password and for all activity under your account.</li>
        <li>Notify us promptly of any unauthorized use of your account.</li>
      </ul>

      <h2>3. Your content and responsibilities</h2>
      <p>
        You retain ownership of the content you submit. You grant us a limited license to host, process,
        and transmit that content solely to operate and provide the Service to you.
      </p>
      <ul>
        <li>
          <strong>You represent and warrant that you have all necessary rights, consents, and authority</strong> to
          provide the personal information of your crew, talent, and contacts, and to have us contact them
          (for example, by emailing call sheets and confirmation links) on your behalf.
        </li>
        <li>
          With respect to that personal information, you act as the controller and we act as your service
          provider, processing it only on your instructions.
        </li>
        <li>You are responsible for complying with applicable privacy, data-protection, and anti-spam laws.</li>
      </ul>

      <h2>4. Acceptable use</h2>
      <p>You agree not to:</p>
      <ul>
        <li>use the Service for any unlawful purpose or to upload information you do not have the right to share;</li>
        <li>attempt to disrupt, overload, attack, or gain unauthorized access to the Service or its systems;</li>
        <li>reverse engineer, scrape, or resell the Service except as permitted by law;</li>
        <li>upload malicious code or content.</li>
      </ul>

      <h2>5. AI-generated content</h2>
      <p>
        Call sheets and related outputs are generated using artificial intelligence and third-party data
        sources (such as weather and nearby-hospital lookups). These outputs may contain errors, omissions,
        or inaccuracies. <strong>You are responsible for reviewing and verifying all information before
        relying on it or distributing it</strong> to your crew. We make no warranty as to the accuracy or
        completeness of generated content.
      </p>

      <h2>6. Third-party services</h2>
      <p>
        The Service relies on third parties for hosting, email delivery, AI processing, and map/weather
        data. We are not responsible for their acts, omissions, or outages, and your use may be subject to
        their terms.
      </p>

      <h2>7. Fees</h2>
      <p>
        The Service is currently free to use during early beta. We may introduce paid plans in the future.
        If we do, we will provide notice before charging you, and continued use of paid features will be
        subject to the applicable pricing and terms.
      </p>

      <h2>8. Intellectual property</h2>
      <p>
        The Service, including its software, design, and branding, is owned by us and our licensors and is
        protected by intellectual-property laws. These Terms do not grant you any rights to our trademarks
        or other branding.
      </p>

      <h2>9. Disclaimers</h2>
      <p>
        THE SERVICE IS PROVIDED &ldquo;AS IS&rdquo; AND &ldquo;AS AVAILABLE,&rdquo; WITHOUT WARRANTIES OF ANY
        KIND, WHETHER EXPRESS OR IMPLIED, INCLUDING IMPLIED WARRANTIES OF MERCHANTABILITY, FITNESS FOR A
        PARTICULAR PURPOSE, AND NON-INFRINGEMENT, TO THE FULLEST EXTENT PERMITTED BY LAW.
      </p>

      <h2>10. Limitation of liability</h2>
      <p>
        TO THE MAXIMUM EXTENT PERMITTED BY LAW, SET&gt;READY WILL NOT BE LIABLE FOR ANY INDIRECT,
        INCIDENTAL, SPECIAL, CONSEQUENTIAL, OR PUNITIVE DAMAGES, OR FOR LOST PROFITS OR DATA. OUR TOTAL
        LIABILITY FOR ANY CLAIM RELATING TO THE SERVICE WILL NOT EXCEED THE GREATER OF THE AMOUNTS YOU PAID
        US IN THE TWELVE MONTHS BEFORE THE CLAIM OR ONE HUNDRED U.S. DOLLARS ($100).
      </p>

      <h2>11. Indemnification</h2>
      <p>
        You agree to indemnify and hold harmless SET&gt;READY from any claims, damages, or expenses arising
        out of your content, your use of the Service, your violation of these Terms, or your sharing of
        another person&rsquo;s personal information without proper authorization.
      </p>

      <h2>12. Termination</h2>
      <p>
        We may suspend or terminate your access if you violate these Terms or to protect the Service. You
        may stop using the Service and request deletion of your account at any time.
      </p>

      <h2>13. Changes to these Terms</h2>
      <p>
        We may update these Terms from time to time. We will revise the &ldquo;Last updated&rdquo; date above,
        and your continued use of the Service after changes take effect constitutes acceptance.
      </p>

      <h2>14. Governing law</h2>
      <p>
        These Terms are governed by the laws of [Jurisdiction], without regard to its conflict-of-laws
        rules. Any disputes will be resolved in the courts located in [Jurisdiction].
      </p>

      <h2>15. Contact us</h2>
      <p>Questions about these Terms? Contact us at support@set-ready-set.com.</p>
    </LegalPage>
  );
}
