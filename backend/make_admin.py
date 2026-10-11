"""Create an administrator account. Run this on the server only; no website page or API route can create one.

    python make_admin.py --name "Lisa" --channel email --contact you@example.com

Administrators sign in on the website with a one-time code, like everyone else, and their session lasts 8 hours.
In test mode (DELIVERY=log) the code is printed in the server log, never shown on the page.
The ADMIN_TOKEN in .env is only for scripts and operators calling the API directly. The website never asks for it."""
import argparse, datetime, sys
import store

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--name", required=True); ap.add_argument("--channel", choices=("sms", "email", "whatsapp"), required=True); ap.add_argument("--contact", required=True)
a = ap.parse_args()
contact = a.contact.strip().replace(" ", "")[:120]; contact = contact.lower() if a.channel == "email" else contact
store.init(); old = store.get_sub(a.channel, contact)
if old and old["role"] != "admin" and old.get("active"):
    sys.exit(f"{contact} is already registered as a {old['role']}. Use a different contact, or have that person stop alerts first.")
now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
store.put_sub({"created": now, "name": a.name.strip()[:80], "role": "admin", "channel": a.channel, "contact": contact, "lat": 0.0, "lon": 0.0, "radius_km": 50,
               "active": 1, "demo": 0, "lang": "en", "share": 0, "profile": {"designation": "Administrator", "consent": {"at": now, "channel": a.channel, "version": 1}}})
print(f"Administrator account ready for {contact}. Sign in on the website with Sign in, then enter the code sent to you.")
