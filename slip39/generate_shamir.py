from . import  create

# Input your 12 or 14-word mnemonic
mnemonic = input("Enter your 12 or 24-word mnemonic: ")

details_ones_using_bip39	= create(
    "SLIP39 Wallet: Backup BIP-39",
    1,
    {'2of3': (2, 3)},
    mnemonic,
    using_bip39 = True,
    #using_bip39 = False,
    iteration_exponent=16
)

#print(details_ones_using_bip39)
print(f"\n{'-'*10} Shamir Shares Details {'-'*10}\n")
print(f"Wallet Name: {details_ones_using_bip39.name}")
print(f"Group Threshold: {details_ones_using_bip39.group_threshold}")
print("\nGroups:")
for group_name, (threshold, mnemonics) in details_ones_using_bip39.groups.items():
    print(f" - {group_name}:")
    print(f"   Threshold: {threshold}")
    print("   Mnemonics:")
    for i, mnemonic in enumerate(mnemonics):
        print(f"     {i + 1}. {mnemonic}")

print("\nAccounts:")
for accounts_crypto in details_ones_using_bip39.accounts:
    for account in accounts_crypto:
        print(f" {account.crypto} (Path: {account.address})")

print(f"\nUsing BIP-39: {details_ones_using_bip39.using_bip39}")
print(f"{'-'*40}\n")
