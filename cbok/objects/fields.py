from oslo_versionedobjects import fields

# Import field errors from oslo.versionedobjects
KeyTypeError = fields.KeyTypeError
ElementTypeError = fields.ElementTypeError


# Import fields from oslo.versionedobjects
BooleanField = fields.BooleanField
UnspecifiedDefault = fields.UnspecifiedDefault
IntegerField = fields.IntegerField
NonNegativeIntegerField = fields.NonNegativeIntegerField
UUIDField = fields.UUIDField
FloatField = fields.FloatField
NonNegativeFloatField = fields.NonNegativeFloatField
StringField = fields.StringField
SensitiveStringField = fields.SensitiveStringField
EnumField = fields.EnumField
DateTimeField = fields.DateTimeField
DictOfStringsField = fields.DictOfStringsField
DictOfNullableStringsField = fields.DictOfNullableStringsField
DictOfIntegersField = fields.DictOfIntegersField
ListOfStringsField = fields.ListOfStringsField
SetOfIntegersField = fields.SetOfIntegersField
ListOfSetsOfIntegersField = fields.ListOfSetsOfIntegersField
ListOfDictOfNullableStringsField = fields.ListOfDictOfNullableStringsField
DictProxyField = fields.DictProxyField
ObjectField = fields.ObjectField
ListOfObjectsField = fields.ListOfObjectsField
VersionPredicateField = fields.VersionPredicateField
FlexibleBooleanField = fields.FlexibleBooleanField
DictOfListOfStringsField = fields.DictOfListOfStringsField
IPAddressField = fields.IPAddressField
IPV4AddressField = fields.IPV4AddressField
IPV6AddressField = fields.IPV6AddressField
IPV4AndV6AddressField = fields.IPV4AndV6AddressField
IPNetworkField = fields.IPNetworkField
IPV4NetworkField = fields.IPV4NetworkField
IPV6NetworkField = fields.IPV6NetworkField
AutoTypedField = fields.AutoTypedField
BaseEnumField = fields.BaseEnumField
MACAddressField = fields.MACAddressField
ListOfIntegersField = fields.ListOfIntegersField
PCIAddressField = fields.PCIAddressField
# NOTE(kodanevhy): These are things we need to import for some of our
# own implementations below, our tests, or other transitional
# bits of code. These should be removable after we finish our
# conversion. So do not use these cbok fields directly in any new code;
# instead, use the oslo.versionedobjects fields.
Enum = fields.Enum
Field = fields.Field
FieldType = fields.FieldType
Set = fields.Set
Dict = fields.Dict
List = fields.List
Object = fields.Object
IPAddress = fields.IPAddress
IPV4Address = fields.IPV4Address
IPV6Address = fields.IPV6Address
IPNetwork = fields.IPNetwork
IPV4Network = fields.IPV4Network
IPV6Network = fields.IPV6Network
