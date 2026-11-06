(() => {
    const moneyFormat = new Intl.NumberFormat('en-UG', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    });

    function amount(value) {
        const numeric = Number(value);
        return `UGX ${moneyFormat.format(Number.isFinite(numeric) ? numeric : 0)}`;
    }

    function setStatus(message, isError = false) {
        const status = document.getElementById('reports-status');
        status.textContent = message;
        status.dataset.error = String(isError);
    }

    function addSummaryCard(container, label, value) {
        const card = document.createElement('article');
        card.className = 'summary-card';
        const title = document.createElement('span');
        title.textContent = label;
        const total = document.createElement('strong');
        total.textContent = value;
        card.append(title, total);
        container.appendChild(card);
    }

    function renderTable(bodyId, rows, columns, emptyMessage) {
        const body = document.getElementById(bodyId);
        body.replaceChildren();
        if (!rows.length) {
            const row = document.createElement('tr');
            const cell = document.createElement('td');
            cell.colSpan = columns.length;
            cell.textContent = emptyMessage;
            row.appendChild(cell);
            body.appendChild(row);
            return;
        }

        rows.forEach(record => {
            const row = document.createElement('tr');
            columns.forEach(([key, formatter]) => {
                const cell = document.createElement('td');
                const value = record[key];
                cell.textContent = formatter ? formatter(value, record) : (value ?? '');
                row.appendChild(cell);
            });
            body.appendChild(row);
        });
    }

    async function loadReport() {
        setStatus('Loading finance report…');
        try {
            const response = await fetch('/api/treasurer-reports/data', {
                credentials: 'include'
            });
            const result = await readApiJson(response, 'Could not load treasurer reports. Please try again.');
            if (!response.ok) {
                throw new Error(result.detail || 'Could not load the finance report.');
            }

            const report = result.data;
            const summary = document.getElementById('reports-summary');
            summary.replaceChildren();
            addSummaryCard(summary, 'Paid subscriptions', amount(report.subscriptions.paid_total));
            addSummaryCard(summary, 'Loan principal outstanding', amount(report.loans.outstanding_balance));
            addSummaryCard(summary, 'Interest collected', amount(report.loans.interest_collected));
            addSummaryCard(summary, 'Sharing payout available', amount(report.sharing.available_payout));
            addSummaryCard(summary, 'Welfare account balance', amount(report.welfare.account_balance));
            addSummaryCard(summary, 'Welfare member arrears', amount(report.welfare.member_arrears));
            document.getElementById('reports-generated').textContent =
                `Generated ${new Date(report.generated_at).toLocaleString()}.`;

            const formatDate = value => value ? String(value).slice(0, 10) : '';
            renderTable('subscription-report', report.subscription_rows, [
                ['id'], ['member_id'], ['full_name'], ['billing_month', formatDate],
                ['amount_paid', amount],
                ['status', (value, row) =>
                    String(value || '').trim().toLowerCase() === 'paid'
                        && Number(row.amount_paid) < Number(report.monthly_subscription_target || 20000)
                        ? 'Partially Paid'
                        : value]
            ], 'No subscription records.');
            renderTable('subscription-proofs-report', report.subscription_proofs, [
                ['proof_id'], ['member_id'], ['member_name'],
                ['subscription_month'], ['subscription_year'],
                ['amount_paid', (value, row) =>
                    value === null
                        ? String(row.verification_status || '').trim().toLowerCase() === 'pending verification'
                            ? 'Awaiting Treasurer verification'
                            : 'Not verified'
                        : amount(value)],
                ['payment_method'], ['transaction_reference'], ['verification_status'],
                ['upload_timestamp', formatDate],
                ['verified_by', (value, row) => value ? `${value} / ${row.verification_date || ''}` : ''],
                ['verification_comment']
            ], 'No subscription payment proofs.');

            renderTable('loan-report', report.loan_rows, [
                ['loan_id'], ['member_id'], ['full_name'], ['applied_date', formatDate],
                ['amount_requested', amount], ['principal_paid', amount],
                ['interest_paid', amount], ['outstanding_balance', amount], ['status']
            ], 'No loan records.');
            renderTable('loan-repayments-report', report.loan_repayment_rows, [
                ['loan_id'], ['member_id'], ['full_name'],
                ['principal_paid', amount], ['interest_paid', amount]
            ], 'No loan repayment transactions.');

            renderTable('sharing-report', report.sharing_rows, [
                ['member_id'], ['full_name'], ['savings', amount],
                ['available_savings', amount],
                ['borrower_dividend', amount], ['group_dividend', amount],
                ['disbursed_amount', amount], ['reserved_amount', amount],
                ['available_payout', amount]
            ], 'No member payout records.');
            renderTable('sharing-withdrawal-report', report.sharing_withdrawal_rows, [
                ['id'], ['member_id'], ['full_name'], ['amount', amount], ['status'],
                ['requested_on', value => value ? String(value).replace('T', ' ') : ''],
                ['approved_by', (value, row) => value ? `${value} / ${row.approved_on || ''}` : ''],
                ['rejected_by', (value, row) => value ? `${value} / ${row.rejected_on || ''}` : ''],
                ['disbursed_by', (value, row) => value ? `${value} / ${row.disbursed_on || ''}` : ''],
                ['review_comment']
            ], 'No sharing withdrawal transactions.');

            renderTable('welfare-report', report.welfare_requests, [
                ['case_number'],
                ['member_name', (value, row) =>
                    `${value || ''} (${row.member_id || ''}) · For: ${row.beneficiary_relationship || ''} ${row.beneficiary_name || 'legacy record'}`],
                ['support_category'],
                ['current_stage', (value, row) => `${row.status || ''} / ${value || ''}`],
                ['created_at', formatDate], ['target_amount', amount],
                ['disbursed_amount', amount], ['welfare_funding', amount],
                ['savings_funding', amount], ['member_arrears', amount],
                ['payment_reference']
            ], 'No welfare requests.');
            renderTable('welfare-disbursement-report', report.welfare_disbursement_rows, [
                ['id'], ['case_number'],
                ['applicant_name', (value, row) =>
                    `${value || ''} (${row.applicant_member_id || ''}) · For: ${row.beneficiary_relationship || ''} ${row.beneficiary_name || 'legacy record'}`],
                ['support_category'], ['target_amount', amount], ['amount', amount],
                ['disbursed_by'], ['disbursed_role'], ['payment_reference'], ['disbursed_at', formatDate]
            ], 'No welfare disbursement transactions.');

                ['case_number'], ['member_id'], ['full_name'], ['contribution_status'],
                ['target_amount', amount],
                ['welfare_amount', amount], ['savings_amount', amount],
                ['outstanding_amount', amount]
            ], 'No welfare contribution records.');
            renderTable('welfare-balances-report', report.welfare_member_balances, [
                ['member_id'], ['full_name'], ['total_contributed', amount],
                ['amount_assessed', amount], ['arrears_paid', amount],
                ['welfare_balance', amount]
            ], 'No member welfare accounts.');
            renderTable('welfare-transfer-report', report.welfare_contribution_rows, [
                ['id'], ['transfer_reference'], ['member_id'], ['full_name'],
                ['amount', amount], ['created_by'], ['created_by_role'], ['created_at', formatDate]
            ], 'No welfare contribution transfers.');
            renderTable('welfare-arrears-report', report.welfare_arrears_payment_rows, [
                ['id'], ['payment_reference'], ['case_number'], ['member_id'],
                ['full_name'], ['amount', amount], ['created_by'], ['created_by_role'],
                ['created_at', formatDate]
            ], 'No welfare arrears repayments.');
            setStatus('Finance report loaded.');
        } catch (error) {
            setStatus(error.message || 'Could not load the finance report.', true);
            console.error('Unable to load Treasurer finance report:', error);
        }
    }

    document.getElementById('reports-refresh')?.addEventListener('click', loadReport);
    loadReport();
})();
