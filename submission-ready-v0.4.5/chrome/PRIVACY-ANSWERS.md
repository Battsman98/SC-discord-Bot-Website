# Chrome Privacy practices answers

## Single purpose

Allow a user to import the names of ships and vehicles in their own RSI pledge hangar into their authenticated SC Companion hangar.

## Host permission justification

`https://robertsspaceindustries.com/*` is required to request the signed-in user's RSI My Hangar pledge pages after the user clicks Import RSI Hangar. Responses are parsed locally. The extension does not read or transmit the RSI cookie value.

`https://sccompanion.org/*` is required for the SC Companion page to initiate the import and receive the locally recognized ship and vehicle names. The service worker rejects messages from other origins.

## Remote code

No. The extension does not download or execute remote JavaScript or WebAssembly. Network responses are processed only as data.

## Data handled

- Website content: RSI My Hangar responses, processed transiently and locally.
- Authentication information: the browser attaches the existing RSI session directly to RSI requests; the extension does not read, store, or transmit the cookie value.
- User-provided content transmitted to SC Companion: recognized ship and vehicle names only.

## Data-use certifications

- Data is used only for the extension's single purpose.
- Data is not sold or transferred for advertising, analytics, creditworthiness, or unrelated purposes.
- Complete RSI HTML, passwords, cookies, billing details, order details, pledge IDs, buybacks, CCUs, paints, and equipment are not transmitted to SC Companion.
- The extension does not access unrelated browsing history.

## Public privacy policy

https://sccompanion.org/rsi-hangar-importer/privacy
