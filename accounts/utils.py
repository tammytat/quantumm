# Save as: accounts/utils.py
import requests
from django.conf import settings

# Official Paystack Bank Codes for Nigeria (CBN standard tracking codes)
BANK_CODES = {
    'Access Bank': '044',
    'Fidelity Bank': '070',
    'First Bank of Nigeria': '011',
    'GTBank': '058',
    'Sterling Bank': '030',
    'UBA': '033',
    'Union Bank': '032',
    'Zenith Bank': '057',
}

def create_paystack_subaccount(teacher_profile):
    """
    Registers a platform teacher as an official vendor subaccount on Paystack.
    Returns the unique 'subaccount_code' (e.g., ACCT_xxxxxxxxx) on success.
    """
    url = "https://api.paystack.co/subaccount"
    headers = {
        "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json"
    }
    
    # Match the human-readable bank name to its specific bank clearing code
    bank_code = BANK_CODES.get(teacher_profile.bank_name, '058') # Defaults to GTB if not found
    
    payload = {
        "business_name": f"{teacher_profile.user.get_full_name() or teacher_profile.user.username} - Labs",
        "settlement_bank": bank_code,
        "account_number": teacher_profile.account_number,
        # Paystack handles the split calculation dynamically per transaction on checkout,
        # but requires a baseline parameter here. We can set it to a 0% default baseline 
        # and pass exact flat split rates later inside the checkout popup modal.
        "percentage_charge": 0.00 
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        response_data = response.json()
        
        if response_data.get('status') == True:
            return response_data['data']['subaccount_code']
        else:
            print(f"❌ Paystack API Rejection Message: {response_data.get('message')}")
            return None
    except Exception as e:
        print(f"❌ Paystack Connection Timeout Exception: {str(e)}")
        return None