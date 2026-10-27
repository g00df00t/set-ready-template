--
-- PostgreSQL database dump
--

\restrict dIlERceXaQ5eml2zwsWgnZCEogYkrxQf50urdkgGVM2c1wFg8pYaC5UgNaPhoWB

-- Dumped from database version 17.6
-- Dumped by pg_dump version 18.6

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: public; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA public;


--
-- Name: SCHEMA public; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON SCHEMA public IS 'standard public schema';


--
-- Name: accessible_owner_ids(uuid); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.accessible_owner_ids(uid uuid) RETURNS SETOF uuid
    LANGUAGE sql STABLE SECURITY DEFINER
    AS $$
  SELECT uid
  UNION
  SELECT owner_id FROM team_members
  WHERE member_user_id = uid AND status = 'accepted';
$$;


--
-- Name: rls_auto_enable(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.rls_auto_enable() RETURNS event_trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog'
    AS $$
DECLARE
  cmd record;
BEGIN
  FOR cmd IN
    SELECT *
    FROM pg_event_trigger_ddl_commands()
    WHERE command_tag IN ('CREATE TABLE', 'CREATE TABLE AS', 'SELECT INTO')
      AND object_type IN ('table','partitioned table')
  LOOP
     IF cmd.schema_name IS NOT NULL AND cmd.schema_name IN ('public') AND cmd.schema_name NOT IN ('pg_catalog','information_schema') AND cmd.schema_name NOT LIKE 'pg_toast%' AND cmd.schema_name NOT LIKE 'pg_temp%' THEN
      BEGIN
        EXECUTE format('alter table if exists %s enable row level security', cmd.object_identity);
        RAISE LOG 'rls_auto_enable: enabled RLS on %', cmd.object_identity;
      EXCEPTION
        WHEN OTHERS THEN
          RAISE LOG 'rls_auto_enable: failed to enable RLS on %', cmd.object_identity;
      END;
     ELSE
        RAISE LOG 'rls_auto_enable: skip % (either system schema or not in enforced list: %.)', cmd.object_identity, cmd.schema_name;
     END IF;
  END LOOP;
END;
$$;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: call_sheet_attachments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.call_sheet_attachments (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    project_id uuid NOT NULL,
    filename text NOT NULL,
    storage_path text NOT NULL,
    content_type text NOT NULL,
    byte_size bigint NOT NULL,
    original_byte_size bigint NOT NULL,
    sort_order integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: call_sheets; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.call_sheets (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    project_id uuid NOT NULL,
    html_content text NOT NULL,
    generated_at timestamp with time zone DEFAULT now(),
    sent_at timestamp with time zone
);


--
-- Name: company_moves; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.company_moves (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    project_id uuid NOT NULL,
    label text,
    location_name text,
    address text,
    parking_notes text,
    additional_notes text,
    move_time time without time zone,
    sort_order integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    parking_address text
);


--
-- Name: crew_members; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.crew_members (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    project_id uuid NOT NULL,
    name text NOT NULL,
    email text NOT NULL,
    role text NOT NULL,
    call_time time without time zone,
    confirmation_token uuid DEFAULT gen_random_uuid(),
    confirmed_at timestamp with time zone,
    phone text,
    department text,
    sort_order integer DEFAULT 0 NOT NULL,
    hide_contact boolean DEFAULT false NOT NULL,
    wants_pdf boolean DEFAULT false NOT NULL,
    last_sent_at timestamp with time zone,
    call_time_note text,
    roster_id uuid,
    deal_memo_dates text,
    hire_id uuid
);


--
-- Name: job_budget_lines; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.job_budget_lines (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    job_id uuid NOT NULL,
    bucket text DEFAULT 'rate'::text NOT NULL,
    block text,
    name text NOT NULL,
    note text,
    flag text,
    qty numeric(8,2),
    unit_amount_cents bigint,
    est_cents bigint,
    act_cents bigint,
    bill_cents bigint,
    markup_bp integer DEFAULT 0 NOT NULL,
    dropped boolean DEFAULT false NOT NULL,
    awaiting_cost boolean DEFAULT false NOT NULL,
    act_paid boolean DEFAULT false NOT NULL,
    floor_kind text,
    sort_order integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    section text,
    cost_final boolean DEFAULT false NOT NULL,
    CONSTRAINT job_budget_lines_bucket_check CHECK ((bucket = ANY (ARRAY['fee'::text, 'rate'::text, 'pass'::text]))),
    CONSTRAINT job_budget_lines_floor_kind_check CHECK (((floor_kind IS NULL) OR (floor_kind = ANY (ARRAY['production_fee'::text, 'insurance'::text, 'contingency'::text])))),
    CONSTRAINT job_budget_lines_money_nonnegative CHECK (((COALESCE(est_cents, (0)::bigint) >= 0) AND (COALESCE(act_cents, (0)::bigint) >= 0) AND (COALESCE(bill_cents, (0)::bigint) >= 0) AND (COALESCE(unit_amount_cents, (0)::bigint) >= 0) AND (markup_bp >= 0)))
);


--
-- Name: job_expenses; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.job_expenses (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    job_id uuid NOT NULL,
    budget_line_id uuid,
    spent_on date,
    payee text,
    description text,
    amount_cents bigint NOT NULL,
    category text DEFAULT 'production_misc'::text NOT NULL,
    sort_order integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    receipt_path text,
    receipt_name text,
    receipt_type text,
    CONSTRAINT job_expenses_amount_cents_check CHECK ((amount_cents >= 0)),
    CONSTRAINT job_expenses_category_check CHECK ((category = ANY (ARRAY['photography'::text, 'video'::text, 'talent'::text, 'stylist_hmu'::text, 'art_props'::text, 'location_studio'::text, 'production_misc'::text, 'producer'::text, 'payroll_fee'::text])))
);


--
-- Name: job_hires; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.job_hires (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    job_id uuid NOT NULL,
    roster_id uuid,
    name text NOT NULL,
    email text,
    phone text,
    role text,
    department text,
    dates_override jsonb DEFAULT '{}'::jsonb NOT NULL,
    sort_order integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    dates_note text,
    rate_shoot numeric(10,2),
    rate_travel numeric(10,2),
    rate_prep numeric(10,2),
    rate_note text,
    rate_source text,
    rate_source_job_id uuid,
    day_notes jsonb DEFAULT '{}'::jsonb NOT NULL,
    away jsonb,
    room_notes text,
    reservations jsonb DEFAULT '{}'::jsonb NOT NULL,
    room_overrides jsonb DEFAULT '{}'::jsonb NOT NULL,
    per_diem_overrides jsonb DEFAULT '{}'::jsonb NOT NULL,
    per_diem_note text,
    per_diem_paid jsonb,
    status text DEFAULT 'confirmed'::text NOT NULL,
    hold_rank smallint,
    kind text DEFAULT 'crew'::text NOT NULL,
    segment text,
    agency_fee_pct numeric(5,2),
    notes text,
    travel_legs jsonb DEFAULT '[]'::jsonb NOT NULL,
    car_service_producer_phone boolean,
    CONSTRAINT job_hires_hold_rank_check CHECK (((hold_rank IS NULL) OR (hold_rank = ANY (ARRAY[1, 2])))),
    CONSTRAINT job_hires_kind_check CHECK ((kind = ANY (ARRAY['crew'::text, 'talent'::text]))),
    CONSTRAINT job_hires_rate_source_check CHECK (((rate_source IS NULL) OR (rate_source = ANY (ARRAY['job'::text, 'roster'::text])))),
    CONSTRAINT job_hires_rates_nonnegative CHECK (((COALESCE(rate_shoot, (0)::numeric) >= (0)::numeric) AND (COALESCE(rate_travel, (0)::numeric) >= (0)::numeric) AND (COALESCE(rate_prep, (0)::numeric) >= (0)::numeric))),
    CONSTRAINT job_hires_status_check CHECK ((status = ANY (ARRAY['hold'::text, 'confirmed'::text, 'released'::text])))
);


--
-- Name: job_invoices; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.job_invoices (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    job_id uuid NOT NULL,
    label text NOT NULL,
    amount_cents bigint NOT NULL,
    issued_on date,
    paid boolean DEFAULT false NOT NULL,
    paid_on date,
    sort_order integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    CONSTRAINT job_invoices_amount_cents_check CHECK ((amount_cents >= 0))
);


--
-- Name: job_pc_log_sends; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.job_pc_log_sends (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    job_id uuid NOT NULL,
    sent_on date NOT NULL,
    snapshot jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: jobs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.jobs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    owner_id uuid NOT NULL,
    name text NOT NULL,
    client_name text,
    production_company text,
    payroll_provider text,
    crew_dates jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    location_line text,
    per_diem_line text,
    per_diem_shoot numeric(10,2),
    per_diem_other numeric(10,2),
    per_diem_paid_by text,
    day_labels jsonb DEFAULT '{}'::jsonb NOT NULL,
    hotels jsonb DEFAULT '[]'::jsonb NOT NULL,
    role_slots jsonb DEFAULT '[]'::jsonb NOT NULL,
    producer_phone text,
    talent_sheet jsonb DEFAULT '{}'::jsonb NOT NULL,
    vendors jsonb DEFAULT '[]'::jsonb NOT NULL,
    usage_dates jsonb DEFAULT '{}'::jsonb NOT NULL,
    production_fee_bp integer DEFAULT 800 NOT NULL,
    pc_log_camera text DEFAULT 'photography'::text NOT NULL,
    pc_log_generated jsonb DEFAULT '{}'::jsonb NOT NULL,
    estimate_signed_on date,
    statement jsonb DEFAULT '{}'::jsonb NOT NULL,
    CONSTRAINT jobs_pc_log_camera_check CHECK ((pc_log_camera = ANY (ARRAY['photography'::text, 'video'::text]))),
    CONSTRAINT jobs_production_fee_bp_check CHECK (((production_fee_bp >= 0) AND (production_fee_bp <= 10000)))
);


--
-- Name: location_roster; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.location_roster (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    owner_id uuid NOT NULL,
    name text NOT NULL,
    address text,
    parking_notes text,
    parking_address text,
    additional_notes text,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: lunch_orders; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.lunch_orders (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    session_id uuid NOT NULL,
    submitter_name text NOT NULL,
    submitter_email text,
    items text NOT NULL,
    dietary_restrictions text,
    submitted_at timestamp with time zone DEFAULT now()
);


--
-- Name: lunch_sessions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.lunch_sessions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    project_id uuid NOT NULL,
    token uuid DEFAULT gen_random_uuid(),
    closes_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now(),
    restaurant_name text,
    menu_url text,
    notes text
);


--
-- Name: productions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.productions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    owner_id uuid NOT NULL,
    name text NOT NULL,
    notes text,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: project_accommodations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.project_accommodations (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    project_id uuid NOT NULL,
    hotel_name text,
    address text,
    phone text,
    website_url text,
    room_block text,
    check_in_time text,
    check_out_time text,
    amenities text,
    notes text
);


--
-- Name: project_contacts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.project_contacts (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    project_id uuid NOT NULL,
    organization text,
    name text NOT NULL,
    role text,
    sort_order integer DEFAULT 0,
    created_at timestamp with time zone DEFAULT now(),
    email text,
    phone text,
    call_time time without time zone,
    wants_pdf boolean DEFAULT true NOT NULL,
    last_sent_at timestamp with time zone,
    call_time_note text,
    roster_id uuid
);


--
-- Name: project_locations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.project_locations (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    project_id uuid NOT NULL,
    location_name text,
    address text,
    parking_notes text,
    additional_notes text,
    parking_address text
);


--
-- Name: project_meals; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.project_meals (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    project_id uuid NOT NULL,
    breakfast_start time without time zone,
    breakfast_end time without time zone,
    breakfast_notes text,
    lunch_start time without time zone,
    lunch_end time without time zone,
    lunch_notes text
);


--
-- Name: projects; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.projects (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    owner_id uuid NOT NULL,
    name text NOT NULL,
    shoot_date date,
    general_call_time time without time zone,
    created_at timestamp with time zone DEFAULT now(),
    notes text,
    production_id uuid,
    day_type text DEFAULT 'shoot'::text NOT NULL,
    day_order integer DEFAULT 0 NOT NULL,
    first_call_time time without time zone,
    first_shot_time time without time zone,
    lunch_time time without time zone,
    est_wrap_time time without time zone,
    wrap_share_token uuid,
    client_name text,
    production_company text,
    payroll_provider text,
    job_id uuid
);


--
-- Name: roster; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.roster (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    owner_id uuid NOT NULL,
    name text NOT NULL,
    email text,
    phone text,
    role text,
    created_at timestamp with time zone DEFAULT now(),
    department text,
    organization text,
    type text DEFAULT 'crew'::text NOT NULL,
    company text,
    day_rate text,
    rate_note text,
    agency text,
    agent_name text,
    agent_email text,
    agent_phone text,
    based text,
    portfolio_url text
);


--
-- Name: schedule_items; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.schedule_items (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    project_id uuid NOT NULL,
    start_time time without time zone NOT NULL,
    end_time time without time zone,
    description text NOT NULL,
    sort_order integer DEFAULT 0
);


--
-- Name: talent; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.talent (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    project_id uuid NOT NULL,
    role text,
    name text NOT NULL,
    phone text,
    email text,
    call_time time without time zone,
    sort_order integer DEFAULT 0,
    created_at timestamp with time zone DEFAULT now(),
    location_assignment text,
    hide_contact boolean DEFAULT true NOT NULL,
    call_time_note text,
    roster_id uuid,
    hire_id uuid
);


--
-- Name: team_members; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.team_members (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    owner_id uuid NOT NULL,
    member_user_id uuid,
    invited_email text NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    invite_token uuid DEFAULT gen_random_uuid() NOT NULL,
    invited_at timestamp with time zone DEFAULT now() NOT NULL,
    accepted_at timestamp with time zone,
    revoked_at timestamp with time zone
);


--
-- Name: usage_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.usage_events (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    project_id uuid,
    event_type text NOT NULL,
    recipient_count integer,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    input_tokens integer,
    output_tokens integer,
    model text,
    CONSTRAINT usage_events_event_type_check CHECK ((event_type = ANY (ARRAY['call_sheet_generated'::text, 'call_sheet_sent'::text, 'call_sheet_reminded'::text, 'wrap_report_viewed'::text, 'wrap_report_shared'::text, 'import_roster_paste'::text, 'import_roster_call_sheet'::text, 'import_crew_paste'::text, 'import_talent_paste'::text, 'import_contacts_paste'::text, 'import_receipt'::text, 'import_estimate'::text]))),
    CONSTRAINT usage_events_tokens_check CHECK ((((input_tokens IS NULL) OR (input_tokens >= 0)) AND ((output_tokens IS NULL) OR (output_tokens >= 0))))
);


--
-- Name: call_sheet_attachments call_sheet_attachments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.call_sheet_attachments
    ADD CONSTRAINT call_sheet_attachments_pkey PRIMARY KEY (id);


--
-- Name: call_sheets call_sheets_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.call_sheets
    ADD CONSTRAINT call_sheets_pkey PRIMARY KEY (id);


--
-- Name: company_moves company_moves_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.company_moves
    ADD CONSTRAINT company_moves_pkey PRIMARY KEY (id);


--
-- Name: crew_members crew_members_confirmation_token_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.crew_members
    ADD CONSTRAINT crew_members_confirmation_token_key UNIQUE (confirmation_token);


--
-- Name: crew_members crew_members_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.crew_members
    ADD CONSTRAINT crew_members_pkey PRIMARY KEY (id);


--
-- Name: job_budget_lines job_budget_lines_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.job_budget_lines
    ADD CONSTRAINT job_budget_lines_pkey PRIMARY KEY (id);


--
-- Name: job_expenses job_expenses_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.job_expenses
    ADD CONSTRAINT job_expenses_pkey PRIMARY KEY (id);


--
-- Name: job_hires job_hires_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.job_hires
    ADD CONSTRAINT job_hires_pkey PRIMARY KEY (id);


--
-- Name: job_invoices job_invoices_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.job_invoices
    ADD CONSTRAINT job_invoices_pkey PRIMARY KEY (id);


--
-- Name: job_pc_log_sends job_pc_log_sends_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.job_pc_log_sends
    ADD CONSTRAINT job_pc_log_sends_pkey PRIMARY KEY (id);


--
-- Name: jobs jobs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.jobs
    ADD CONSTRAINT jobs_pkey PRIMARY KEY (id);


--
-- Name: location_roster location_roster_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.location_roster
    ADD CONSTRAINT location_roster_pkey PRIMARY KEY (id);


--
-- Name: lunch_orders lunch_orders_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lunch_orders
    ADD CONSTRAINT lunch_orders_pkey PRIMARY KEY (id);


--
-- Name: lunch_sessions lunch_sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lunch_sessions
    ADD CONSTRAINT lunch_sessions_pkey PRIMARY KEY (id);


--
-- Name: lunch_sessions lunch_sessions_token_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lunch_sessions
    ADD CONSTRAINT lunch_sessions_token_key UNIQUE (token);


--
-- Name: productions productions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.productions
    ADD CONSTRAINT productions_pkey PRIMARY KEY (id);


--
-- Name: project_accommodations project_accommodations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_accommodations
    ADD CONSTRAINT project_accommodations_pkey PRIMARY KEY (id);


--
-- Name: project_accommodations project_accommodations_project_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_accommodations
    ADD CONSTRAINT project_accommodations_project_id_key UNIQUE (project_id);


--
-- Name: project_contacts project_contacts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_contacts
    ADD CONSTRAINT project_contacts_pkey PRIMARY KEY (id);


--
-- Name: project_locations project_locations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_locations
    ADD CONSTRAINT project_locations_pkey PRIMARY KEY (id);


--
-- Name: project_locations project_locations_project_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_locations
    ADD CONSTRAINT project_locations_project_id_key UNIQUE (project_id);


--
-- Name: project_meals project_meals_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_meals
    ADD CONSTRAINT project_meals_pkey PRIMARY KEY (id);


--
-- Name: project_meals project_meals_project_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_meals
    ADD CONSTRAINT project_meals_project_id_key UNIQUE (project_id);


--
-- Name: projects projects_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.projects
    ADD CONSTRAINT projects_pkey PRIMARY KEY (id);


--
-- Name: roster roster_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.roster
    ADD CONSTRAINT roster_pkey PRIMARY KEY (id);


--
-- Name: schedule_items schedule_items_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.schedule_items
    ADD CONSTRAINT schedule_items_pkey PRIMARY KEY (id);


--
-- Name: talent talent_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.talent
    ADD CONSTRAINT talent_pkey PRIMARY KEY (id);


--
-- Name: team_members team_members_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.team_members
    ADD CONSTRAINT team_members_pkey PRIMARY KEY (id);


--
-- Name: usage_events usage_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.usage_events
    ADD CONSTRAINT usage_events_pkey PRIMARY KEY (id);


--
-- Name: crew_members_hire_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX crew_members_hire_id_idx ON public.crew_members USING btree (hire_id);


--
-- Name: crew_members_roster_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX crew_members_roster_id_idx ON public.crew_members USING btree (roster_id);


--
-- Name: job_budget_lines_job_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX job_budget_lines_job_id_idx ON public.job_budget_lines USING btree (job_id);


--
-- Name: job_expenses_job_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX job_expenses_job_id_idx ON public.job_expenses USING btree (job_id);


--
-- Name: job_expenses_line_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX job_expenses_line_id_idx ON public.job_expenses USING btree (budget_line_id);


--
-- Name: job_hires_job_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX job_hires_job_id_idx ON public.job_hires USING btree (job_id);


--
-- Name: job_hires_roster_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX job_hires_roster_id_idx ON public.job_hires USING btree (roster_id);


--
-- Name: job_invoices_job_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX job_invoices_job_id_idx ON public.job_invoices USING btree (job_id);


--
-- Name: job_pc_log_sends_job_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX job_pc_log_sends_job_id_idx ON public.job_pc_log_sends USING btree (job_id);


--
-- Name: jobs_owner_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX jobs_owner_id_idx ON public.jobs USING btree (owner_id);


--
-- Name: project_contacts_roster_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX project_contacts_roster_id_idx ON public.project_contacts USING btree (roster_id);


--
-- Name: projects_job_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX projects_job_id_idx ON public.projects USING btree (job_id);


--
-- Name: projects_wrap_share_token_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX projects_wrap_share_token_idx ON public.projects USING btree (wrap_share_token) WHERE (wrap_share_token IS NOT NULL);


--
-- Name: talent_roster_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX talent_roster_id_idx ON public.talent USING btree (roster_id);


--
-- Name: team_members_invite_token_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX team_members_invite_token_idx ON public.team_members USING btree (invite_token);


--
-- Name: team_members_member_user_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX team_members_member_user_id_idx ON public.team_members USING btree (member_user_id) WHERE (status = 'accepted'::text);


--
-- Name: team_members_owner_id_invited_email_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX team_members_owner_id_invited_email_idx ON public.team_members USING btree (owner_id, invited_email) WHERE (status = ANY (ARRAY['pending'::text, 'accepted'::text]));


--
-- Name: usage_events_created_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX usage_events_created_idx ON public.usage_events USING btree (created_at DESC);


--
-- Name: usage_events_user_created_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX usage_events_user_created_idx ON public.usage_events USING btree (user_id, created_at DESC);


--
-- Name: call_sheet_attachments call_sheet_attachments_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.call_sheet_attachments
    ADD CONSTRAINT call_sheet_attachments_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;


--
-- Name: call_sheets call_sheets_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.call_sheets
    ADD CONSTRAINT call_sheets_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;


--
-- Name: company_moves company_moves_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.company_moves
    ADD CONSTRAINT company_moves_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;


--
-- Name: crew_members crew_members_hire_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.crew_members
    ADD CONSTRAINT crew_members_hire_id_fkey FOREIGN KEY (hire_id) REFERENCES public.job_hires(id) ON DELETE SET NULL;


--
-- Name: crew_members crew_members_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.crew_members
    ADD CONSTRAINT crew_members_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;


--
-- Name: crew_members crew_members_roster_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.crew_members
    ADD CONSTRAINT crew_members_roster_id_fkey FOREIGN KEY (roster_id) REFERENCES public.roster(id) ON DELETE SET NULL;


--
-- Name: job_budget_lines job_budget_lines_job_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.job_budget_lines
    ADD CONSTRAINT job_budget_lines_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.jobs(id) ON DELETE CASCADE;


--
-- Name: job_expenses job_expenses_budget_line_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.job_expenses
    ADD CONSTRAINT job_expenses_budget_line_id_fkey FOREIGN KEY (budget_line_id) REFERENCES public.job_budget_lines(id) ON DELETE SET NULL;


--
-- Name: job_expenses job_expenses_job_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.job_expenses
    ADD CONSTRAINT job_expenses_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.jobs(id) ON DELETE CASCADE;


--
-- Name: job_hires job_hires_job_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.job_hires
    ADD CONSTRAINT job_hires_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.jobs(id) ON DELETE CASCADE;


--
-- Name: job_hires job_hires_rate_source_job_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.job_hires
    ADD CONSTRAINT job_hires_rate_source_job_id_fkey FOREIGN KEY (rate_source_job_id) REFERENCES public.jobs(id) ON DELETE SET NULL;


--
-- Name: job_hires job_hires_roster_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.job_hires
    ADD CONSTRAINT job_hires_roster_id_fkey FOREIGN KEY (roster_id) REFERENCES public.roster(id) ON DELETE SET NULL;


--
-- Name: job_invoices job_invoices_job_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.job_invoices
    ADD CONSTRAINT job_invoices_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.jobs(id) ON DELETE CASCADE;


--
-- Name: job_pc_log_sends job_pc_log_sends_job_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.job_pc_log_sends
    ADD CONSTRAINT job_pc_log_sends_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.jobs(id) ON DELETE CASCADE;


--
-- Name: jobs jobs_owner_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.jobs
    ADD CONSTRAINT jobs_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES auth.users(id) ON DELETE CASCADE;


--
-- Name: location_roster location_roster_owner_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.location_roster
    ADD CONSTRAINT location_roster_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES auth.users(id) ON DELETE CASCADE;


--
-- Name: lunch_orders lunch_orders_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lunch_orders
    ADD CONSTRAINT lunch_orders_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.lunch_sessions(id) ON DELETE CASCADE;


--
-- Name: lunch_sessions lunch_sessions_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lunch_sessions
    ADD CONSTRAINT lunch_sessions_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;


--
-- Name: productions productions_owner_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.productions
    ADD CONSTRAINT productions_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES auth.users(id) ON DELETE CASCADE;


--
-- Name: project_accommodations project_accommodations_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_accommodations
    ADD CONSTRAINT project_accommodations_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;


--
-- Name: project_contacts project_contacts_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_contacts
    ADD CONSTRAINT project_contacts_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;


--
-- Name: project_contacts project_contacts_roster_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_contacts
    ADD CONSTRAINT project_contacts_roster_id_fkey FOREIGN KEY (roster_id) REFERENCES public.roster(id) ON DELETE SET NULL;


--
-- Name: project_locations project_locations_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_locations
    ADD CONSTRAINT project_locations_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;


--
-- Name: project_meals project_meals_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_meals
    ADD CONSTRAINT project_meals_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;


--
-- Name: projects projects_job_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.projects
    ADD CONSTRAINT projects_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.jobs(id) ON DELETE CASCADE;


--
-- Name: projects projects_owner_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.projects
    ADD CONSTRAINT projects_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES auth.users(id) ON DELETE CASCADE;


--
-- Name: projects projects_production_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.projects
    ADD CONSTRAINT projects_production_id_fkey FOREIGN KEY (production_id) REFERENCES public.productions(id) ON DELETE CASCADE;


--
-- Name: roster roster_owner_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.roster
    ADD CONSTRAINT roster_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES auth.users(id) ON DELETE CASCADE;


--
-- Name: schedule_items schedule_items_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.schedule_items
    ADD CONSTRAINT schedule_items_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;


--
-- Name: talent talent_hire_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.talent
    ADD CONSTRAINT talent_hire_id_fkey FOREIGN KEY (hire_id) REFERENCES public.job_hires(id) ON DELETE SET NULL;


--
-- Name: talent talent_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.talent
    ADD CONSTRAINT talent_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;


--
-- Name: talent talent_roster_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.talent
    ADD CONSTRAINT talent_roster_id_fkey FOREIGN KEY (roster_id) REFERENCES public.roster(id) ON DELETE SET NULL;


--
-- Name: team_members team_members_member_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.team_members
    ADD CONSTRAINT team_members_member_user_id_fkey FOREIGN KEY (member_user_id) REFERENCES auth.users(id) ON DELETE CASCADE;


--
-- Name: team_members team_members_owner_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.team_members
    ADD CONSTRAINT team_members_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES auth.users(id) ON DELETE CASCADE;


--
-- Name: usage_events usage_events_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.usage_events
    ADD CONSTRAINT usage_events_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE SET NULL;


--
-- Name: usage_events usage_events_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.usage_events
    ADD CONSTRAINT usage_events_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE;


--
-- Name: call_sheet_attachments; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.call_sheet_attachments ENABLE ROW LEVEL SECURITY;

--
-- Name: call_sheets; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.call_sheets ENABLE ROW LEVEL SECURITY;

--
-- Name: company_moves; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.company_moves ENABLE ROW LEVEL SECURITY;

--
-- Name: crew_members; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.crew_members ENABLE ROW LEVEL SECURITY;

--
-- Name: job_budget_lines; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.job_budget_lines ENABLE ROW LEVEL SECURITY;

--
-- Name: job_expenses; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.job_expenses ENABLE ROW LEVEL SECURITY;

--
-- Name: job_hires; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.job_hires ENABLE ROW LEVEL SECURITY;

--
-- Name: job_invoices; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.job_invoices ENABLE ROW LEVEL SECURITY;

--
-- Name: job_pc_log_sends; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.job_pc_log_sends ENABLE ROW LEVEL SECURITY;

--
-- Name: jobs; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.jobs ENABLE ROW LEVEL SECURITY;

--
-- Name: location_roster; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.location_roster ENABLE ROW LEVEL SECURITY;

--
-- Name: lunch_orders; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.lunch_orders ENABLE ROW LEVEL SECURITY;

--
-- Name: lunch_sessions; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.lunch_sessions ENABLE ROW LEVEL SECURITY;

--
-- Name: team_members member reads own membership; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "member reads own membership" ON public.team_members FOR SELECT USING ((member_user_id = auth.uid()));


--
-- Name: team_members owner manages team; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "owner manages team" ON public.team_members USING ((owner_id = auth.uid())) WITH CHECK ((owner_id = auth.uid()));


--
-- Name: company_moves owner_all; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY owner_all ON public.company_moves USING ((project_id IN ( SELECT projects.id
   FROM public.projects
  WHERE (projects.owner_id IN ( SELECT public.accessible_owner_ids(auth.uid()) AS accessible_owner_ids)))));


--
-- Name: project_accommodations owners manage accommodations; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "owners manage accommodations" ON public.project_accommodations USING ((project_id IN ( SELECT projects.id
   FROM public.projects
  WHERE (projects.owner_id IN ( SELECT public.accessible_owner_ids(auth.uid()) AS accessible_owner_ids)))));


--
-- Name: call_sheet_attachments owners manage call sheet attachments; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "owners manage call sheet attachments" ON public.call_sheet_attachments USING ((project_id IN ( SELECT projects.id
   FROM public.projects
  WHERE (projects.owner_id IN ( SELECT public.accessible_owner_ids(auth.uid()) AS accessible_owner_ids)))));


--
-- Name: call_sheets owners manage call sheets; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "owners manage call sheets" ON public.call_sheets USING ((project_id IN ( SELECT projects.id
   FROM public.projects
  WHERE (projects.owner_id IN ( SELECT public.accessible_owner_ids(auth.uid()) AS accessible_owner_ids)))));


--
-- Name: project_contacts owners manage contacts; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "owners manage contacts" ON public.project_contacts USING ((project_id IN ( SELECT projects.id
   FROM public.projects
  WHERE (projects.owner_id IN ( SELECT public.accessible_owner_ids(auth.uid()) AS accessible_owner_ids)))));


--
-- Name: crew_members owners manage crew; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "owners manage crew" ON public.crew_members USING ((project_id IN ( SELECT projects.id
   FROM public.projects
  WHERE (projects.owner_id IN ( SELECT public.accessible_owner_ids(auth.uid()) AS accessible_owner_ids)))));


--
-- Name: job_budget_lines owners manage job budget lines; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "owners manage job budget lines" ON public.job_budget_lines USING ((job_id IN ( SELECT jobs.id
   FROM public.jobs
  WHERE (jobs.owner_id IN ( SELECT public.accessible_owner_ids(auth.uid()) AS accessible_owner_ids))))) WITH CHECK ((job_id IN ( SELECT jobs.id
   FROM public.jobs
  WHERE (jobs.owner_id IN ( SELECT public.accessible_owner_ids(auth.uid()) AS accessible_owner_ids)))));


--
-- Name: job_expenses owners manage job expenses; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "owners manage job expenses" ON public.job_expenses USING ((job_id IN ( SELECT jobs.id
   FROM public.jobs
  WHERE (jobs.owner_id IN ( SELECT public.accessible_owner_ids(auth.uid()) AS accessible_owner_ids))))) WITH CHECK ((job_id IN ( SELECT jobs.id
   FROM public.jobs
  WHERE (jobs.owner_id IN ( SELECT public.accessible_owner_ids(auth.uid()) AS accessible_owner_ids)))));


--
-- Name: job_hires owners manage job hires; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "owners manage job hires" ON public.job_hires USING ((job_id IN ( SELECT jobs.id
   FROM public.jobs
  WHERE (jobs.owner_id IN ( SELECT public.accessible_owner_ids(auth.uid()) AS accessible_owner_ids))))) WITH CHECK ((job_id IN ( SELECT jobs.id
   FROM public.jobs
  WHERE (jobs.owner_id IN ( SELECT public.accessible_owner_ids(auth.uid()) AS accessible_owner_ids)))));


--
-- Name: job_invoices owners manage job invoices; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "owners manage job invoices" ON public.job_invoices USING ((job_id IN ( SELECT jobs.id
   FROM public.jobs
  WHERE (jobs.owner_id IN ( SELECT public.accessible_owner_ids(auth.uid()) AS accessible_owner_ids))))) WITH CHECK ((job_id IN ( SELECT jobs.id
   FROM public.jobs
  WHERE (jobs.owner_id IN ( SELECT public.accessible_owner_ids(auth.uid()) AS accessible_owner_ids)))));


--
-- Name: job_pc_log_sends owners manage job pc log sends; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "owners manage job pc log sends" ON public.job_pc_log_sends USING ((job_id IN ( SELECT jobs.id
   FROM public.jobs
  WHERE (jobs.owner_id IN ( SELECT public.accessible_owner_ids(auth.uid()) AS accessible_owner_ids))))) WITH CHECK ((job_id IN ( SELECT jobs.id
   FROM public.jobs
  WHERE (jobs.owner_id IN ( SELECT public.accessible_owner_ids(auth.uid()) AS accessible_owner_ids)))));


--
-- Name: jobs owners manage jobs; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "owners manage jobs" ON public.jobs USING ((owner_id IN ( SELECT public.accessible_owner_ids(auth.uid()) AS accessible_owner_ids))) WITH CHECK ((owner_id IN ( SELECT public.accessible_owner_ids(auth.uid()) AS accessible_owner_ids)));


--
-- Name: location_roster owners manage location roster; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "owners manage location roster" ON public.location_roster USING ((owner_id IN ( SELECT public.accessible_owner_ids(auth.uid()) AS accessible_owner_ids)));


--
-- Name: project_locations owners manage locations; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "owners manage locations" ON public.project_locations USING ((project_id IN ( SELECT projects.id
   FROM public.projects
  WHERE (projects.owner_id IN ( SELECT public.accessible_owner_ids(auth.uid()) AS accessible_owner_ids)))));


--
-- Name: lunch_orders owners manage lunch orders; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "owners manage lunch orders" ON public.lunch_orders USING ((session_id IN ( SELECT ls.id
   FROM (public.lunch_sessions ls
     JOIN public.projects p ON ((p.id = ls.project_id)))
  WHERE (p.owner_id = auth.uid()))));


--
-- Name: lunch_sessions owners manage lunch sessions; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "owners manage lunch sessions" ON public.lunch_sessions USING ((project_id IN ( SELECT projects.id
   FROM public.projects
  WHERE (projects.owner_id = auth.uid()))));


--
-- Name: project_meals owners manage meals; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "owners manage meals" ON public.project_meals USING ((project_id IN ( SELECT projects.id
   FROM public.projects
  WHERE (projects.owner_id IN ( SELECT public.accessible_owner_ids(auth.uid()) AS accessible_owner_ids)))));


--
-- Name: productions owners manage productions; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "owners manage productions" ON public.productions USING ((owner_id = auth.uid()));


--
-- Name: projects owners manage projects; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "owners manage projects" ON public.projects USING ((owner_id IN ( SELECT public.accessible_owner_ids(auth.uid()) AS accessible_owner_ids)));


--
-- Name: schedule_items owners manage schedule; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "owners manage schedule" ON public.schedule_items USING ((project_id IN ( SELECT projects.id
   FROM public.projects
  WHERE (projects.owner_id IN ( SELECT public.accessible_owner_ids(auth.uid()) AS accessible_owner_ids)))));


--
-- Name: talent owners manage talent; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "owners manage talent" ON public.talent USING ((project_id IN ( SELECT projects.id
   FROM public.projects
  WHERE (projects.owner_id IN ( SELECT public.accessible_owner_ids(auth.uid()) AS accessible_owner_ids)))));


--
-- Name: productions; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.productions ENABLE ROW LEVEL SECURITY;

--
-- Name: project_accommodations; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.project_accommodations ENABLE ROW LEVEL SECURITY;

--
-- Name: project_contacts; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.project_contacts ENABLE ROW LEVEL SECURITY;

--
-- Name: project_locations; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.project_locations ENABLE ROW LEVEL SECURITY;

--
-- Name: project_meals; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.project_meals ENABLE ROW LEVEL SECURITY;

--
-- Name: projects; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.projects ENABLE ROW LEVEL SECURITY;

--
-- Name: roster; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.roster ENABLE ROW LEVEL SECURITY;

--
-- Name: schedule_items; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.schedule_items ENABLE ROW LEVEL SECURITY;

--
-- Name: talent; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.talent ENABLE ROW LEVEL SECURITY;

--
-- Name: team_members; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.team_members ENABLE ROW LEVEL SECURITY;

--
-- Name: usage_events; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.usage_events ENABLE ROW LEVEL SECURITY;

--
-- Name: roster users manage own roster; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "users manage own roster" ON public.roster USING ((owner_id IN ( SELECT public.accessible_owner_ids(auth.uid()) AS accessible_owner_ids)));


--
-- PostgreSQL database dump complete
--

\unrestrict dIlERceXaQ5eml2zwsWgnZCEogYkrxQf50urdkgGVM2c1wFg8pYaC5UgNaPhoWB

