"""Create demo accounts + listings so judges can try MandiLink instantly.

    python -m app.seed

Demo accounts are clearly named "(Demo)" and are NOT counted as real traction.
"""
from __future__ import annotations

import asyncio

from sqlmodel import Session, select

from .db import engine, init_db
from .models import BuyRequest, Listing, User
from .security import hash_pin
from .services import bootstrap

DEMO = [
    ("u_demo_farmer", "Haripada Mondal (Demo)", "9000000001", "farmer", "bn", "Hooghly"),
    ("u_demo_buyer", "Rohit Agarwal (Demo)", "9000000002", "buyer", "en", "Kolkata"),
    ("u_demo_trader", "Sunita Devi (Demo)", "9000000003", "buyer", "hi", "Asansol"),
    ("u_demo_farmer2", "Rina Bibi (Demo)", "9000000004", "farmer", "bn", "Nadia"),
]
LISTINGS = [
    ("u_demo_farmer", "potato", "Jyoti", 2500, 14.0, "Hooghly", "A", "Cold-storage Jyoti potato, medium size, cleaned and bagged (50 kg)."),
    ("u_demo_farmer", "cauliflower", "Snowball", 600, 18.0, "Hooghly", "A", "Fresh harvest, tight white curds. Can deliver to Sealdah."),
    ("u_demo_farmer2", "jute", "Tossa", 1200, 52.0, "Nadia", "B", "Tossa jute fibre, retted and dried, golden colour."),
    ("u_demo_farmer2", "brinjal", "Muktakeshi", 400, 19.0, "Nadia", "A", "Round brinjal, pesticide-light, picked this morning."),
    ("u_demo_farmer", "rice", "Miniket", 800, 36.0, "Hooghly", "A", "Miniket rice, new crop, milled and packed in 25 kg bags."),
]

REQUESTS = [
    ("u_demo_trader", "potato", 1000, 13.0, "Asansol", "Weekly supply for my shop, Jyoti preferred."),
    ("u_demo_buyer", "mustard", 500, 58.0, "Kolkata", "For oil mill, clean and dry seed."),
]


async def main() -> None:
    init_db()
    with Session(engine) as s:
        await bootstrap(s)
        for uid, name, phone, role, lang, district in DEMO:
            if s.get(User, uid) is None:
                s.add(User(id=uid, name=name, phone=phone, pin_hash=hash_pin("1234"), role=role,
                           language=lang, district=district))
        s.commit()
        if not s.exec(select(Listing)).first():
            for seller, crop, variety, qty, price, district, grade, desc in LISTINGS:
                s.add(Listing(seller_id=seller, crop=crop, variety=variety, quantity_kg=qty, price_per_kg=price,
                              district=district, grade=grade, description=desc))
            s.commit()
        if not s.exec(select(BuyRequest)).first():
            for buyer, crop, qty, price, district, note in REQUESTS:
                s.add(BuyRequest(buyer_id=buyer, crop=crop, quantity_kg=qty, target_price_per_kg=price,
                                 district=district, note=note))
            s.commit()
    print("Seeded demo data. Demo PIN for all demo accounts: 1234")
    for _, name, phone, role, lang, _ in DEMO:
        print(f"  {role:7} {phone}  {name}  [{lang}]")
    print("  agent   9000000000  Riya · MandiLink Support  (PIN = SUPPORT_AGENT_PIN, default 2468)")


if __name__ == "__main__":
    asyncio.run(main())
