## TODO 

Time comparisons

Same month across years (trend + % change)
Current month vs last month (net pay, employer cost, insurance, count)
YTD vs prior YTD (absolute + % change)
Rolling 12‑month trend with YoY overlay

Cost structure

Payroll mix by document type (salary/bonus/allowance)
Employer cost vs net pay ratio over time
Insurance burden % (insurance / total cost)

Workforce

Headcount trend + new/left employees
Top contributors (top N employees by cost)
Median vs average net pay (distribution health)

Payment status

Paid vs unpaid totals + aging buckets
Average days to paid (payment_date → paid_date)
Anomalies

Outlier net pay / insurance by z‑score or % threshold
Sudden jumps per employee or per document type

3.0.2


2. i want to enhance the document upload functionality to scan proof of money transfer and the app should recognize for which employee this was and assign payment amount and automaticaly make paid==true. also it should get the payment date. the amount is recognizable from paid_amount == monthly net_pay

3. this payment receipt should also be merged with the monthly payment pdfs. 

4. we should also add fields: signed_employer and signed_employee both boolean. 
a monthly pdf with the payment receipt should be signed by employer and employee. could we automate that if i drop the signed documents the program could recognize the signed documents?

