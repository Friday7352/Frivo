Test certificates for `units.test.js`, made with openssl and valid for ten
years. These are public certificates only. Their private keys were thrown
away, so nothing here can sign or serve anything.

- `frivo-ca.pem`: an authority like the one Frivo makes ("Frivo Local CA")
- `frivo-leaf.pem`: a server certificate signed by it
- `rogue-ca.pem`: another authority with the same name
- `rogue-leaf.pem`: a server certificate signed by the rogue one
