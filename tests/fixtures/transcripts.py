"""10 fixed transcripts for the M2 gate: 5 scams that must trigger, 5 legit calls that must not.
Each entry is a list of (speaker, text). Detection runs after every caller turn, like production."""

C, L = "caller", "receiver"

SCAMS = {
    "digital_arrest": [
        (C, "Hello, this is Inspector Rathore from the Mumbai cyber crime branch. Am I speaking with Mister Sharma?"),
        (L, "Yes, speaking. What is this about?"),
        (C, "A parcel in your name was caught at customs with drugs and fake passports. A case has been filed against you."),
        (L, "I never sent any parcel!"),
        (C, "Your Aadhaar was used. Do not disconnect this call and do not tell anyone, or we will send police to arrest you today."),
        (L, "Please, what do I do?"),
        (C, "Transfer fifty thousand rupees to this RBI safe verification account immediately to clear your name."),
    ],
    "bank_kyc_otp": [
        (C, "Good afternoon sir, I am calling from State Bank head office. Your KYC has expired and your account will be blocked today."),
        (L, "Blocked? I have my pension in that account."),
        (C, "Do not worry, I can update it right now. You will get an OTP on your phone, please read out the six digit code to me."),
        (L, "Okay, it says four eight one nine two zero."),
        (C, "Thank you. Now also tell me your ATM card number and the PIN to complete verification."),
    ],
    "courier_customs_fee": [
        (C, "This is FedEx customs department. A package from abroad is held in your name and has restricted items."),
        (L, "I was not expecting anything."),
        (C, "You must pay a clearance fine of twenty five thousand rupees within one hour or the package goes to the police."),
        (L, "How do I pay?"),
        (C, "Send it by UPI to this ID, customs dot clear at okbank, right now, and stay on the line until I confirm."),
    ],
    "remote_access_support": [
        (C, "Hello, I am calling from Microsoft technical support. Your computer has sent us virus alerts and hackers are stealing your bank data."),
        (L, "Oh no, what should I do?"),
        (C, "Please open your browser and download AnyDesk. Then tell me the nine digit code so I can fix it on your screen."),
        (L, "Okay, I am installing it."),
        (C, "Good. Do not close it and do not tell your family, they will panic. After this you must pay a two thousand rupee security fee by gift card."),
    ],
    "fake_relative_emergency": [
        (C, "Hello uncle, it is me, Rohan. I am in big trouble, please do not tell Mummy or Papa."),
        (L, "Rohan? What happened?"),
        (C, "I had an accident and the police are here, they will arrest me unless I pay today. Please send twenty thousand on UPI right now."),
        (L, "Where do I send it?"),
        (C, "Send to this number, nine eight seven six five four three two one zero on PhonePe, quickly, and please keep it a secret."),
    ],
}

LEGIT = {
    "bank_fraud_team_no_otp": [
        (C, "Hello, this is Priya from the fraud monitoring team at your bank. We saw a card transaction in Dubai, was that you?"),
        (L, "No, I have never been to Dubai."),
        (C, "Thank you, we have blocked the card and a new one will be posted to your address. Please note we will never ask for your OTP or PIN."),
        (L, "Okay, good to know."),
        (C, "You can also visit your home branch with your ID anytime. Have a good day."),
    ],
    "delivery_otp_safe_mention": [
        (C, "Hi, I am the delivery person from Amazon, I am outside your gate with your order."),
        (L, "Oh yes, I will come down."),
        (C, "Sir, the delivery code was sent to your app. Please show it to me in person, never read it out on a phone call to anyone else."),
        (L, "Alright, I have it on my screen."),
    ],
    "doctor_appointment": [
        (C, "Hello, this is Dr. Mehta's clinic. I am calling to confirm your appointment tomorrow at ten thirty."),
        (L, "Yes, I will be there."),
        (C, "Please bring your previous reports. The consultation fee is five hundred rupees, you can pay at the counter."),
        (L, "Okay, thank you."),
    ],
    "family_chat": [
        (C, "Hi Papa, it is me. I reached Pune safely, the train was on time."),
        (L, "Good, did you eat something?"),
        (C, "Yes, and I will call you on Sunday. Tell Mummy not to worry. Take your medicines."),
    ],
    "telemarketing_hardneg_police": [
        (C, "Good morning, I am calling from a home insurance company. Can I take two minutes to tell you about our plan?"),
        (L, "I am not interested."),
        (C, "No problem, sir. By the way, if anyone calls claiming to be police and asks for money, please hang up and call one nine three zero. Have a nice day."),
    ],
}
