# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

<!-- version list -->

## v0.6.0 (2026-09-29)

### Bug Fixes

- **application**: Accept every index-prefix code Table 4-6 allows
  ([#112](https://github.com/craigpnnl/dnp3py/pull/112),
  [`cdafe55`](https://github.com/craigpnnl/dnp3py/commit/cdafe550bb4766e385faab39014d51036784f3aa))

- **application**: Frame size-prefixed free-format blocks
  ([#82](https://github.com/craigpnnl/dnp3py/pull/82),
  [`d7a66a9`](https://github.com/craigpnnl/dnp3py/commit/d7a66a9b325f8ae818e5dd692a6fc1a8df2053b8))

- **application**: Read the 256-octet extension for attribute type 255
  ([#82](https://github.com/craigpnnl/dnp3py/pull/82),
  [`4e53607`](https://github.com/craigpnnl/dnp3py/commit/4e53607599768e1c69deb67b8692d2079e6204f7))

- **application**: Refuse qualifiers Table 4-6 does not allow
  ([#112](https://github.com/craigpnnl/dnp3py/pull/112),
  [`cd1c7c7`](https://github.com/craigpnnl/dnp3py/commit/cd1c7c7132c23e5a13286859805c24525c71971c))

- **application**: Reject a malformed group 0 qualifier before the walk
  ([#82](https://github.com/craigpnnl/dnp3py/pull/82),
  [`b36b201`](https://github.com/craigpnnl/dnp3py/commit/b36b2017c23983c7cb95a435108b540f47abbfe3))

- **application**: Reserve qualifier 0x0B, not treat it as an unsupported range
  ([#112](https://github.com/craigpnnl/dnp3py/pull/112),
  [`42deb9f`](https://github.com/craigpnnl/dnp3py/commit/42deb9fcb1b521d0a414415516b700bc2261eb16))

- **database**: Refuse NaN analog input at construction and update
  ([#159](https://github.com/craigpnnl/dnp3py/pull/159),
  [`52eed91`](https://github.com/craigpnnl/dnp3py/commit/52eed91c746a7f4e729fe0e82ac6572a36595b16))

- **database**: Validate last_event_value for NaN in AnalogInputPoint
  ([#159](https://github.com/craigpnnl/dnp3py/pull/159),
  [`2a61fd6`](https://github.com/craigpnnl/dnp3py/commit/2a61fd6e59ab2191a82c76b0e19f619ef9ad9797))

- **datalink**: Make frame resynchronization iterative
  ([#64](https://github.com/craigpnnl/dnp3py/pull/64),
  [`d01d215`](https://github.com/craigpnnl/dnp3py/commit/d01d2155b58018c9b3e3b24ccc526a12360f8e4c))

- **datalink**: Reject LENGTH below the header-only minimum
  ([#65](https://github.com/craigpnnl/dnp3py/pull/65),
  [`77c22c8`](https://github.com/craigpnnl/dnp3py/commit/77c22c8a30bbb0b1bc37986735f435dc3fa33a7f))

- **datalink**: Resync when a header's LENGTH is below 5
  ([#65](https://github.com/craigpnnl/dnp3py/pull/65),
  [`011127a`](https://github.com/craigpnnl/dnp3py/commit/011127a90a0a01ddfbea39635d6635651eda69d2))

- **master**: Narrow process_response to the parser's ParseError
  ([#66](https://github.com/craigpnnl/dnp3py/pull/66),
  [`6cb0a0f`](https://github.com/craigpnnl/dnp3py/commit/6cb0a0fe1fe45692e412d9fde37b532530fc86a6))

- **mesa**: Refuse NaN in analog output validation and store
  ([#171](https://github.com/craigpnnl/dnp3py/pull/171),
  [`dfbfb64`](https://github.com/craigpnnl/dnp3py/commit/dfbfb64534da332520a6c08a513f94f7a6b020a2))

- **objects**: Bound g110 and g111 octet-string variation to 1-255
  ([#82](https://github.com/craigpnnl/dnp3py/pull/82),
  [`7f46de0`](https://github.com/craigpnnl/dnp3py/commit/7f46de0107b938451109afe6992b35cfa6c9bd71))

- **objects**: Correct g101 BCD widths to 2, 4, 8 octets
  ([#82](https://github.com/craigpnnl/dnp3py/pull/82),
  [`18bffbb`](https://github.com/craigpnnl/dnp3py/commit/18bffbb2bc95889b6ef1e5977c031cc14044f130))

- **outstation**: Accept a status from either CommandStatus enum or a matching int
  ([#46](https://github.com/craigpnnl/dnp3py/pull/46),
  [`0b5b6de`](https://github.com/craigpnnl/dnp3py/commit/0b5b6deaa71978fcdb4e637cd4df1d8cb06b5d35))

- **outstation**: Answer a dispatch handler exception with IIN2.2
  ([#46](https://github.com/craigpnnl/dnp3py/pull/46),
  [`a9341f4`](https://github.com/craigpnnl/dnp3py/commit/a9341f490eeb9731c1ef808e438e87eb51280f7e))

- **outstation**: Check the stop before a per-object parse rejection
  ([#46](https://github.com/craigpnnl/dnp3py/pull/46),
  [`531ca8b`](https://github.com/craigpnnl/dnp3py/commit/531ca8b4524e8bef22bc099eef9094fcc79c76ff))

- **outstation**: Correct the fail-closed docstring and log the function by name
  ([#46](https://github.com/craigpnnl/dnp3py/pull/46),
  [`14374e5`](https://github.com/craigpnnl/dnp3py/commit/14374e51ce8fba5f1fd7e5d983b13352781024c1))

- **outstation**: Do not encode a buffered event twice when a request names its class through two
  blocks ([#46](https://github.com/craigpnnl/dnp3py/pull/46),
  [`0c9e777`](https://github.com/craigpnnl/dnp3py/commit/0c9e7779e426c204285fcf489b2644d08066c2f6))

- **outstation**: Drop internal rule labels from failure-logging comments
  ([#46](https://github.com/craigpnnl/dnp3py/pull/46),
  [`a9aadcf`](https://github.com/craigpnnl/dnp3py/commit/a9aadcfa1ded02562d7eb2dfc61dbd0f91d73f5d))

- **outstation**: Guard the analog output lookup, not just the update
  ([#46](https://github.com/craigpnnl/dnp3py/pull/46),
  [`bec371a`](https://github.com/craigpnnl/dnp3py/commit/bec371a930af6d2d469a71dacc49892b72171420))

- **outstation**: Keep buffered events until the response built from them succeeds
  ([#46](https://github.com/craigpnnl/dnp3py/pull/46),
  [`5cc286a`](https://github.com/craigpnnl/dnp3py/commit/5cc286a94600843adddd0dd4d6e5f2352671b185))

- **outstation**: Key event dedup and removal by class and serial, not serial alone
  ([#46](https://github.com/craigpnnl/dnp3py/pull/46),
  [`2dccc9f`](https://github.com/craigpnnl/dnp3py/commit/2dccc9f07b549893c8e299a2cc62b2e214ec7d12))

- **outstation**: Make two log messages name the actual failure
  ([#46](https://github.com/craigpnnl/dnp3py/pull/46),
  [`18c3fb5`](https://github.com/craigpnnl/dnp3py/commit/18c3fb510b9d2bdcb4932257a82514dcde5452ec))

- **outstation**: Rate-limit handler failure logs and add a failure counter
  ([#46](https://github.com/craigpnnl/dnp3py/pull/46),
  [`549d192`](https://github.com/craigpnnl/dnp3py/commit/549d1923cfcb2695fb50e5419e11908ceee84e37))

- **outstation**: Rate-limit the NaN refusal warning under its own key
  ([#46](https://github.com/craigpnnl/dnp3py/pull/46),
  [`171f8dc`](https://github.com/craigpnnl/dnp3py/commit/171f8dc4afae4a4f8f298606da654bc4a8b16ec0))

- **outstation**: Refuse an unrelated int subclass as a control status
  ([#46](https://github.com/craigpnnl/dnp3py/pull/46),
  [`4978d82`](https://github.com/craigpnnl/dnp3py/commit/4978d829149ccb28d6a5b3894f5ab7a718df2b59))

- **outstation**: Report over-range analog input as its limit with OVER_RANGE
  ([#159](https://github.com/craigpnnl/dnp3py/pull/159),
  [`7edc286`](https://github.com/craigpnnl/dnp3py/commit/7edc286f86886173f7813f1a955496ceae1eacf0))

- **outstation**: Require the handler method name for a control point failure
  ([#46](https://github.com/craigpnnl/dnp3py/pull/46),
  [`b49e5c0`](https://github.com/craigpnnl/dnp3py/commit/b49e5c09865c6654e0802f541e9b9ce1f7858fb3))

- **outstation**: State the suppressed count relative to the previous record
  ([#46](https://github.com/craigpnnl/dnp3py/pull/46),
  [`15d6b36`](https://github.com/craigpnnl/dnp3py/commit/15d6b367566ed9c00b771c3ff4c8004a5cb485f8))

- **outstation**: Stop a control request at the first raising point
  ([#46](https://github.com/craigpnnl/dnp3py/pull/46),
  [`f1daee5`](https://github.com/craigpnnl/dnp3py/commit/f1daee562bbf28567b4a1977e8d06cdefbccd3b8))

### Chores

- **tests**: Replace em-dash with hyphen in test_command_handler.py comment
  ([`21553ca`](https://github.com/craigpnnl/dnp3py/commit/21553caddbda9bf2c30702d52b30fd86397c8753))

### Code Style

- **application**: Apply ruff format to the EX 5-2 test
  ([`32c16a3`](https://github.com/craigpnnl/dnp3py/commit/32c16a3f40c90ac5f972f48849f419b529de44a5))

- **application**: Name the attribute type/length window's magic 2
  ([#82](https://github.com/craigpnnl/dnp3py/pull/82),
  [`966b5f4`](https://github.com/craigpnnl/dnp3py/commit/966b5f45cf1151455754937995af945c3b660338))

- **tests**: Format the resync tests with CI's ruff
  ([#64](https://github.com/craigpnnl/dnp3py/pull/64),
  [`4494be4`](https://github.com/craigpnnl/dnp3py/commit/4494be4a5a37095b710da10dab4bb786bec8faf5))

- **tests**: Run ruff format on the new framing test file
  ([#82](https://github.com/craigpnnl/dnp3py/pull/82),
  [`ed960cc`](https://github.com/craigpnnl/dnp3py/commit/ed960cc8142487821e08640db2570fd9e891f668))

### Continuous Integration

- Give every CI job a timeout ([#157](https://github.com/craigpnnl/dnp3py/pull/157),
  [`dd2cb1d`](https://github.com/craigpnnl/dnp3py/commit/dd2cb1d6e29735ce8adc138f827b3284820507a7))

### Documentation

- Add a security policy with private reporting instructions
  ([#180](https://github.com/craigpnnl/dnp3py/pull/180),
  [`e2ebeec`](https://github.com/craigpnnl/dnp3py/commit/e2ebeec018606a8dca8d8ea591606ac53f5fb7ab))

- **application**: Correct the free-format fixture comment's payload claim
  ([#82](https://github.com/craigpnnl/dnp3py/pull/82),
  [`597b02f`](https://github.com/craigpnnl/dnp3py/commit/597b02ffcc7048e8fb49f91484356824463fb8a5))

- **application**: Correct the g111 addressing-note citation
  ([#82](https://github.com/craigpnnl/dnp3py/pull/82),
  [`dd59cd8`](https://github.com/craigpnnl/dnp3py/commit/dd59cd8a96af3c58abf63f0c35444d75adf7bd0b))

- **application**: Correct the valid-qualifier count and the gap reason
  ([#112](https://github.com/craigpnnl/dnp3py/pull/112),
  [`ab6fab2`](https://github.com/craigpnnl/dnp3py/commit/ab6fab20d7bdf02690b9d31e94ad6b26d886cf07))

- **application**: Describe what SIZE_PREFIX and RESERVED_QUALIFIER cover
  ([#112](https://github.com/craigpnnl/dnp3py/pull/112),
  [`157cf58`](https://github.com/craigpnnl/dnp3py/commit/157cf58388a6b746d5d270d7455eaf604535a293))

- **application**: Drop the closed 0xB gap from the UNSUPPORTED_RANGE comment
  ([#82](https://github.com/craigpnnl/dnp3py/pull/82),
  [`b144ed1`](https://github.com/craigpnnl/dnp3py/commit/b144ed174c6543627c26481b5e409397cf32b513))

- **changelog**: Repair the compare-link footer for 0.3.2 to 0.5.0
  ([#40](https://github.com/craigpnnl/dnp3py/pull/40),
  [`c54792e`](https://github.com/craigpnnl/dnp3py/commit/c54792eb5edcec9c5096ef360acdf6c476634580))

- **datalink**: Paraphrase the minimum LENGTH clause
  ([#65](https://github.com/craigpnnl/dnp3py/pull/65),
  [`6eac26e`](https://github.com/craigpnnl/dnp3py/commit/6eac26e7cd450518a75355e1870a722fae25c26c))

- **master**: Document process_response's ParseError-only contract
  ([#66](https://github.com/craigpnnl/dnp3py/pull/66),
  [`9da80cc`](https://github.com/craigpnnl/dnp3py/commit/9da80cc81327cb9edcf3e3c0d7e64ef6b068584c))

- **objects**: Paraphrase the A.41.1.2.2 length-cap comment
  ([#82](https://github.com/craigpnnl/dnp3py/pull/82),
  [`2dab644`](https://github.com/craigpnnl/dnp3py/commit/2dab6447e4839f433123b97d90b9c28c9264c2ee))

- **outstation**: Cite 10.3.3.2 generally for the discard-on-repeat rule
  ([#46](https://github.com/craigpnnl/dnp3py/pull/46),
  [`8a9baf2`](https://github.com/craigpnnl/dnp3py/commit/8a9baf2f796f3d227a925c727658e9c98501b380))

- **outstation**: Correct a stale NaN claim in _clamp_int_range
  ([#159](https://github.com/craigpnnl/dnp3py/pull/159),
  [`7387302`](https://github.com/craigpnnl/dnp3py/commit/7387302e498c6820d353e59b269ee085c352b265))

- **outstation**: Drop quoted standard text from comments
  ([#46](https://github.com/craigpnnl/dnp3py/pull/46),
  [`de5f373`](https://github.com/craigpnnl/dnp3py/commit/de5f373375d11dcca5a06bbfd10dd4077df94811))

- **outstation**: Drop the internal slice label from the docstring
  ([#46](https://github.com/craigpnnl/dnp3py/pull/46),
  [`3e3ea02`](https://github.com/craigpnnl/dnp3py/commit/3e3ea02ad8f5512535b77359242844e31a7eec61))

- **outstation**: State both OPERATE and DIRECT_OPERATE retry behaviour
  ([#46](https://github.com/craigpnnl/dnp3py/pull/46),
  [`c298471`](https://github.com/craigpnnl/dnp3py/commit/c298471f36cb42496dcb77337b2977ff4e275a30))

### Features

- **application**: Frame group 0 attribute values as their own TLV width
  ([#82](https://github.com/craigpnnl/dnp3py/pull/82),
  [`10a4520`](https://github.com/craigpnnl/dnp3py/commit/10a45201d7964687c318440fd8a9cc27575c03ec))

- **objects**: Add fixed-width layout rows for non-measurement objects
  ([#82](https://github.com/craigpnnl/dnp3py/pull/82),
  [`349317d`](https://github.com/craigpnnl/dnp3py/commit/349317d1a8a1dbcdaa4aca835415093db48801cd))

- **objects**: Size g110 and g111 octet strings by variation
  ([#82](https://github.com/craigpnnl/dnp3py/pull/82),
  [`e77ff50`](https://github.com/craigpnnl/dnp3py/commit/e77ff50c16a2a94bed15f200e8b17fae03e04439))

### Refactoring

- **outstation**: Require the stop flag on every control processor
  ([#46](https://github.com/craigpnnl/dnp3py/pull/46),
  [`301ae86`](https://github.com/craigpnnl/dnp3py/commit/301ae866736c5d8ad1b0df301a56fa5a6e22d41a))

### Testing

- **application**: Correct the g120 qualifier note in the class docstring
  ([#82](https://github.com/craigpnnl/dnp3py/pull/82),
  [`3562eba`](https://github.com/craigpnnl/dnp3py/commit/3562eba7f32eca504f83c5b48efdb570d83f0126))

- **application**: Cover a group 0 block naming more than one object
  ([#82](https://github.com/craigpnnl/dnp3py/pull/82),
  [`54ada49`](https://github.com/craigpnnl/dnp3py/commit/54ada4962f3d41a62babe6aca820cf3915ee0dcf))

- **application**: Cover a group 0 block with nothing after it
  ([#82](https://github.com/craigpnnl/dnp3py/pull/82),
  [`7020843`](https://github.com/craigpnnl/dnp3py/commit/702084363ec8ebdfe006cff660876d46bde8fda2))

- **application**: Frame every free-format group ahead of a following block
  ([#82](https://github.com/craigpnnl/dnp3py/pull/82),
  [`1d32c2e`](https://github.com/craigpnnl/dnp3py/commit/1d32c2eab6ccacf1325b91b2e8706b171599b8b3))

- **application**: Frame g110 and g111 blocks past their declared width
  ([#82](https://github.com/craigpnnl/dnp3py/pull/82),
  [`9bf8df0`](https://github.com/craigpnnl/dnp3py/commit/9bf8df045d4b3bd44e27df9113b0725e9e93183d))

- **application**: Frame g110 and g111 with qualifier 0x28 and 0x00, and pin variation 0 as still
  unknown width ([#82](https://github.com/craigpnnl/dnp3py/pull/82),
  [`a16b7b7`](https://github.com/craigpnnl/dnp3py/commit/a16b7b720f6382899c5c5eaf8b5c3f7b37528ebc))

- **application**: Frame size-prefixed qualifiers in the qualifier table tests
  ([#82](https://github.com/craigpnnl/dnp3py/pull/82),
  [`b280289`](https://github.com/craigpnnl/dnp3py/commit/b2802893aa8ddeaf554153baf11953f162670193))

- **application**: Keep an earlier block ahead of a truncated group 0 one
  ([#82](https://github.com/craigpnnl/dnp3py/pull/82),
  [`19a3904`](https://github.com/craigpnnl/dnp3py/commit/19a390462aa06638e1315b7593b911360165a8ff))

- **application**: Keep group 0 variations 0 and 254 refused
  ([#82](https://github.com/craigpnnl/dnp3py/pull/82),
  [`be786e5`](https://github.com/craigpnnl/dnp3py/commit/be786e5639b66343cb36f08e4061f651ca6361de))

- **application**: Pin a zero-length object exactly filling the data
  ([#82](https://github.com/craigpnnl/dnp3py/pull/82),
  [`ed38068`](https://github.com/craigpnnl/dnp3py/commit/ed38068f3271d264c86138024c862950a3565709))

- **application**: Pin count 0 as a valid empty free-format block
  ([#82](https://github.com/craigpnnl/dnp3py/pull/82),
  [`66cf578`](https://github.com/craigpnnl/dnp3py/commit/66cf578c77037b0ca1de64ff3cd6947ee9726b8e))

- **application**: Pin g0v1 as data-carrying, not unsized
  ([#82](https://github.com/craigpnnl/dnp3py/pull/82),
  [`01604c1`](https://github.com/craigpnnl/dnp3py/commit/01604c136387c6a9d2287a773950fa83af415845))

- **application**: Pin g101v1 width from hand-encoded BCD octets
  ([#82](https://github.com/craigpnnl/dnp3py/pull/82),
  [`a3767ad`](https://github.com/craigpnnl/dnp3py/commit/a3767ad18df3e14daef55ee66f85345ab161cc2e))

- **application**: Pin get_range_size(FREE_FORMAT) at its own row
  ([#82](https://github.com/craigpnnl/dnp3py/pull/82),
  [`762378b`](https://github.com/craigpnnl/dnp3py/commit/762378be47f97c3b46202b458333ff913634a396))

- **application**: Pin the free-format file READ from the standard's example
  ([`f8f72f8`](https://github.com/craigpnnl/dnp3py/commit/f8f72f8ba81e8b78c196e3f649a57db36f40493f))

- **application**: Prove g70 free-format framing across all three prefix widths
  ([#82](https://github.com/craigpnnl/dnp3py/pull/82),
  [`c69857e`](https://github.com/craigpnnl/dnp3py/commit/c69857e54babeba457e16bd4f2634d7c5ca85075))

- **application**: Read a declared size from the whole size field
  ([#82](https://github.com/craigpnnl/dnp3py/pull/82),
  [`fe1b1fa`](https://github.com/craigpnnl/dnp3py/commit/fe1b1fa6390b58bd2fc5028b8f885dfea836ca55))

- **application**: Refuse a truncated group 0 attribute window
  ([#82](https://github.com/craigpnnl/dnp3py/pull/82),
  [`8a8c9a1`](https://github.com/craigpnnl/dnp3py/commit/8a8c9a186bd903fbe3a8e1c43c419f81cea88e49))

- **application**: Refuse a truncated size field of zero octets
  ([#82](https://github.com/craigpnnl/dnp3py/pull/82),
  [`31822c6`](https://github.com/craigpnnl/dnp3py/commit/31822c622e77aad01d2f4d6b2aaa65cc312b8020))

- **application**: State the g120v2 qualifier guidance correctly
  ([#82](https://github.com/craigpnnl/dnp3py/pull/82),
  [`1f0870b`](https://github.com/craigpnnl/dnp3py/commit/1f0870bfb3653220c3c35cc74bd5586a633a81df))

- **coverage_gaps**: Pass stop= to the four processor calls missing it
  ([#46](https://github.com/craigpnnl/dnp3py/pull/46),
  [`f4dd946`](https://github.com/craigpnnl/dnp3py/commit/f4dd9467185504fa060b7b1aa28621fbc76da8a2))

- **database**: Cover the NaN analog input refusal at every boundary
  ([#159](https://github.com/craigpnnl/dnp3py/pull/159),
  [`01a8c92`](https://github.com/craigpnnl/dnp3py/commit/01a8c92d83e086674adec27f2bff7db1e7016357))

- **database**: Strengthen mutant coverage and validate last_event_value
  ([#159](https://github.com/craigpnnl/dnp3py/pull/159),
  [`383ee68`](https://github.com/craigpnnl/dnp3py/commit/383ee68644e09578cf35632a35ebd98efb6cc2d4))

- **datalink**: Compare delivered frames by to_bytes, split at odd offset
  ([#64](https://github.com/craigpnnl/dnp3py/pull/64),
  [`8a5b376`](https://github.com/craigpnnl/dnp3py/commit/8a5b376979e4059fc0f58bcfb118b210d9ee3895))

- **datalink**: Fail fast, not hang, if a CRC branch stops consuming bytes
  ([#64](https://github.com/craigpnnl/dnp3py/pull/64),
  [`185d551`](https://github.com/craigpnnl/dnp3py/commit/185d5513d3800ea247b12e80fc26f435ad7efa77))

- **datalink**: Overlap, split-feed and refusal-site coverage for #65
  ([`e95fcf9`](https://github.com/craigpnnl/dnp3py/commit/e95fcf9dfbdc695bc26695016076a953b0c4e97b))

- **datalink**: Prove data-block CRC failure keeps hunting in one feed
  ([#64](https://github.com/craigpnnl/dnp3py/pull/64),
  [`84bfbb8`](https://github.com/craigpnnl/dnp3py/commit/84bfbb87e76d9cf6fb9903d39386ad1c0fe851a0))

- **datalink**: Prove no RecursionError over 3000 bad data blocks
  ([#64](https://github.com/craigpnnl/dnp3py/pull/64),
  [`c3244f2`](https://github.com/craigpnnl/dnp3py/commit/c3244f2f36c04e1e0fa69d3ea958e60e615ce645))

- **master**: Confirm g110 and g111 blocks deliver nothing
  ([#82](https://github.com/craigpnnl/dnp3py/pull/82),
  [`709e82a`](https://github.com/craigpnnl/dnp3py/commit/709e82ac03d02874cbd5bc4f845661168aeb65f9))

- **master**: Cover ValueError and IndexError in non-ParseError propagation
  ([#66](https://github.com/craigpnnl/dnp3py/pull/66),
  [`beea965`](https://github.com/craigpnnl/dnp3py/commit/beea965c841a3e91cbca77ec2e4b27af95bbe306))

- **master**: Pin a full-length fragment with an unknown function code
  ([#66](https://github.com/craigpnnl/dnp3py/pull/66),
  [`ff09598`](https://github.com/craigpnnl/dnp3py/commit/ff095982ad38db387b37b7015d943e88b40b3a73))

- **master**: Pin each new kind's own point kind against the undelivered set
  ([#82](https://github.com/craigpnnl/dnp3py/pull/82),
  [`ceb7c54`](https://github.com/craigpnnl/dnp3py/commit/ceb7c5498de85a4f22928e78bd81d865c4384b51))

- **master**: Pin the five new PointKinds as undelivered
  ([#82](https://github.com/craigpnnl/dnp3py/pull/82),
  [`d3fc8bc`](https://github.com/craigpnnl/dnp3py/commit/d3fc8bcaf5a7c95de03f34339200bbc59c509059))

- **mesa**: Cover the NaN refusal in MesaCommandHandler and its AO store
  ([#171](https://github.com/craigpnnl/dnp3py/pull/171),
  [`567ee84`](https://github.com/craigpnnl/dnp3py/commit/567ee847abc70df5b2403c2894c8279cc4e415ba))

- **outstation**: Assert g32v1 quality is carried from the event, not fixed
  ([#159](https://github.com/craigpnnl/dnp3py/pull/159),
  [`8530fda`](https://github.com/craigpnnl/dnp3py/commit/8530fda07e992b58e02adc3e4d6c383ff4c2d127))

- **outstation**: Assert literal wire bytes and full buffer drain on event tests
  ([#46](https://github.com/craigpnnl/dnp3py/pull/46),
  [`c30977f`](https://github.com/craigpnnl/dnp3py/commit/c30977f43c06e43a66c732715b3a8c7a871b271f))

- **outstation**: Assert the coercion on _run_control_point's return, not the wire byte
  ([#46](https://github.com/craigpnnl/dnp3py/pull/46),
  [`cb089b0`](https://github.com/craigpnnl/dnp3py/commit/cb089b0ad386c162efa8ffaf79c8112da8ed1059))

- **outstation**: Build one over-range expected value from literals
  ([#159](https://github.com/craigpnnl/dnp3py/pull/159),
  [`80ba7eb`](https://github.com/craigpnnl/dnp3py/commit/80ba7ebb6da80cbf6b6603ca50320f50d87313e6))

- **outstation**: Close mutant-survival gaps in the event dedup tests
  ([#46](https://github.com/craigpnnl/dnp3py/pull/46),
  [`68dfdb7`](https://github.com/craigpnnl/dnp3py/commit/68dfdb716d1b088b1dc4286d82f29da48236b0ed))

- **outstation**: Cover a None or False status, and an unrelated IntEnum
  ([#46](https://github.com/craigpnnl/dnp3py/pull/46),
  [`8b117ca`](https://github.com/craigpnnl/dnp3py/commit/8b117ca2501956bd622a62435b5a964ecf8391b0))

- **outstation**: Cover accepted status forms, the parse-order fix, cross-block stops and a raising
  lookup ([#46](https://github.com/craigpnnl/dnp3py/pull/46),
  [`c6a7c5e`](https://github.com/craigpnnl/dnp3py/commit/c6a7c5e06b9d09506c77878a6f94ed8090aa4c2d))

- **outstation**: Cover rate-limited failure logging
  ([#46](https://github.com/craigpnnl/dnp3py/pull/46),
  [`d2c94b9`](https://github.com/craigpnnl/dnp3py/commit/d2c94b9c5514c3c78ac1fa04717694dee4942a18))

- **outstation**: Cover the ERROR log record on every reachable no-ack raise
  ([#46](https://github.com/craigpnnl/dnp3py/pull/46),
  [`1e2e993`](https://github.com/craigpnnl/dnp3py/commit/1e2e993ca66039b865998634c0f22f1f67156142))

- **outstation**: Cover the per-point control guard
  ([#46](https://github.com/craigpnnl/dnp3py/pull/46),
  [`ddfcf69`](https://github.com/craigpnnl/dnp3py/commit/ddfcf6926f71590dbe8036b1a20ac662d529f3c6))

- **outstation**: Cover the rate limiter's window boundary, key fields and warning path
  ([#46](https://github.com/craigpnnl/dnp3py/pull/46),
  [`cf77f35`](https://github.com/craigpnnl/dnp3py/commit/cf77f3597f8198de23c1196921a2c3a5591693d2))

- **outstation**: Cover the stop-before-parse order for SELECT and OPERATE
  ([#46](https://github.com/craigpnnl/dnp3py/pull/46),
  [`35456f9`](https://github.com/craigpnnl/dnp3py/commit/35456f9824b9851bb79d0967f176de8aa9fe01e2))

- **outstation**: Drive the SELECT timer tests with a fake clock
  ([#160](https://github.com/craigpnnl/dnp3py/pull/160),
  [`75f5718`](https://github.com/craigpnnl/dnp3py/commit/75f5718683d996b94b5f973473fc912b0c35bd7f))

- **outstation**: Drop a test of Python's int(), trim docstring narrative
  ([#159](https://github.com/craigpnnl/dnp3py/pull/159),
  [`57eb6d8`](https://github.com/craigpnnl/dnp3py/commit/57eb6d8f5d88909c7fb68cef6ffeb838c0850beb))

- **outstation**: Drop internal item labels from time-write test docstrings
  ([#46](https://github.com/craigpnnl/dnp3py/pull/46),
  [`7b6912c`](https://github.com/craigpnnl/dnp3py/commit/7b6912c77e9b698c81c24104e5fcc713d81db2a7))

- **outstation**: Drop private item-number references from new test docstrings
  ([#46](https://github.com/craigpnnl/dnp3py/pull/46),
  [`1892748`](https://github.com/craigpnnl/dnp3py/commit/1892748e4e56e705a8c9dd39c44f700b1ad54e50))

- **outstation**: Make the logged-function-name assertion exact
  ([#46](https://github.com/craigpnnl/dnp3py/pull/46),
  [`ea27d9a`](https://github.com/craigpnnl/dnp3py/commit/ea27d9a8aa9dd44f588e4306dbe2323fa917c38f))

- **outstation**: Make the select-armed assertion able to fail
  ([#46](https://github.com/craigpnnl/dnp3py/pull/46),
  [`3d6e208`](https://github.com/craigpnnl/dnp3py/commit/3d6e208f0e8dc3032ce5485a2a84bcf859e29d95))

- **outstation**: Move control-raise tests to the per-point echo
  ([#46](https://github.com/craigpnnl/dnp3py/pull/46),
  [`bb44e81`](https://github.com/craigpnnl/dnp3py/commit/bb44e8130254859f845ed72e1432f9e297fdf506))

- **outstation**: Move select-sequence raise tests to the per-point echo
  ([#46](https://github.com/craigpnnl/dnp3py/pull/46),
  [`2710a6a`](https://github.com/craigpnnl/dnp3py/commit/2710a6a4647a1ee6e8b7d2e1362424f4e3d9d0ae))

- **outstation**: Pass the handler method to a direct control point call
  ([#46](https://github.com/craigpnnl/dnp3py/pull/46),
  [`dc9cf43`](https://github.com/craigpnnl/dnp3py/commit/dc9cf43083931fdc4169da6e921ce5324c7979bc))

- **outstation**: Pin int() truncation and true-value boundary for the analog clamp
  ([#159](https://github.com/craigpnnl/dnp3py/pull/159),
  [`dd07514`](https://github.com/craigpnnl/dnp3py/commit/dd075147166e4e7d306ee1aefde2941d96f4c039))

- **outstation**: Pin that an existing OVER_RANGE bit survives an in-range value
  ([#159](https://github.com/craigpnnl/dnp3py/pull/159),
  [`5e28017`](https://github.com/craigpnnl/dnp3py/commit/5e28017c1ea75012a721a192dbf00ed444a2cdca))

- **outstation**: Rename the caller-quality test class to match what it tests
  ([#159](https://github.com/craigpnnl/dnp3py/pull/159),
  [`0b90b60`](https://github.com/craigpnnl/dnp3py/commit/0b90b602c1f503fce86af6f6b711241059998fd7))

- **outstation**: State the tracking-failure test's purpose without internal labels
  ([#46](https://github.com/craigpnnl/dnp3py/pull/46),
  [`7839a3d`](https://github.com/craigpnnl/dnp3py/commit/7839a3dcf09aff2af0fc410f943d220f05f11438))

- **request**: Frame a WRITE of g110/g111 and pin the outstation's write-path answer
  ([#82](https://github.com/craigpnnl/dnp3py/pull/82),
  [`7062a09`](https://github.com/craigpnnl/dnp3py/commit/7062a0909e59129751627e600f0b6f8abc384ec0))


## v0.5.0 (2026-09-29)

### Bug Fixes

- Correlate responses, filter source, and bound the master exchange
  ([`9d45d62`](https://github.com/craigpnnl/dnp3py/commit/9d45d62b0ab662796f2c0ed0f6984542ece3ab12))

- **core**: Range-check ControlCode.from_fields and pin the kept API
  ([#70](https://github.com/craigpnnl/dnp3py/pull/70),
  [`a5ca1c2`](https://github.com/craigpnnl/dnp3py/commit/a5ca1c2416e07cecf9aff311e484c8c6f523dff8))

- **database**: Refuse NaN and non-NONE event class at analog output construction
  ([#122](https://github.com/craigpnnl/dnp3py/pull/122),
  [`55a54a9`](https://github.com/craigpnnl/dnp3py/commit/55a54a9bdaefdddc3e2f8f057563b2593809f5ce))

- **database**: State the group 42 fact plainly in analog output docstrings
  ([#122](https://github.com/craigpnnl/dnp3py/pull/122),
  [`3385edd`](https://github.com/craigpnnl/dnp3py/commit/3385eddb37df4553e92650e1f019e52e13c0de67))

- **master**: Confirm unsolicited responses with UNS set, only on CON
  ([#57](https://github.com/craigpnnl/dnp3py/pull/57),
  [`3ceb626`](https://github.com/craigpnnl/dnp3py/commit/3ceb626b82efa1fee97c23dae99ff3791aa6c552))

- **master**: Count a relative time past year 9999 as untimed
  ([#81](https://github.com/craigpnnl/dnp3py/pull/81),
  [`e729fc3`](https://github.com/craigpnnl/dnp3py/commit/e729fc3290e55f0758209597ea6c30fd8bfbb058))

- **master**: Decode frozen counters g21v5 and g21v6 with flag and time
  ([#79](https://github.com/craigpnnl/dnp3py/pull/79),
  [`115b153`](https://github.com/craigpnnl/dnp3py/commit/115b153b152c6c9c9eab9c6374de2fcf2b6e2b7b))

- **master**: Deliver decoded values in fragment order
  ([`07cb4c8`](https://github.com/craigpnnl/dnp3py/commit/07cb4c803317a51fd4d9c0f1e8696b3d46df130d))

- **master**: Deliver nothing from a block shorter than it declares
  ([#103](https://github.com/craigpnnl/dnp3py/pull/103),
  [`fb31489`](https://github.com/craigpnnl/dnp3py/commit/fb31489f153ddbbde5d3afe34141898b4ceaef69))

- **master**: Deliver nothing from a short packed double-bit block
  ([#103](https://github.com/craigpnnl/dnp3py/pull/103),
  [`eaf02cb`](https://github.com/craigpnnl/dnp3py/commit/eaf02cb856924734ea19a01c1cb1f1d5bb7051c0))

- **master**: Drop a first response fragment for another request
  ([#57](https://github.com/craigpnnl/dnp3py/pull/57),
  [`e04007f`](https://github.com/craigpnnl/dnp3py/commit/e04007fce19acce9e4845b07dd6a186ef257f6f4))

- **master**: Leave nothing half-open when MasterTcpRunner.open() fails
  ([#57](https://github.com/craigpnnl/dnp3py/pull/57),
  [`7c61c88`](https://github.com/craigpnnl/dnp3py/commit/7c61c88e97387bc412cd769c8cb8bb3ce36889ee))

- **master**: Log a warning when a response is cut short
  ([#103](https://github.com/craigpnnl/dnp3py/pull/103),
  [`8dd7787`](https://github.com/craigpnnl/dnp3py/commit/8dd7787a89f6fe7cedb21d7ff5c4a0912a05cd4b))

- **master**: Never deliver on a spent deadline, never strand an owed CONFIRM
  ([#57](https://github.com/craigpnnl/dnp3py/pull/57),
  [`49af103`](https://github.com/craigpnnl/dnp3py/commit/49af10377638fe46ab257e5416eff43e6b25c1f4))

- **master**: Refuse a packed binary block that carries an index prefix
  ([#74](https://github.com/craigpnnl/dnp3py/pull/74),
  [`57aedf5`](https://github.com/craigpnnl/dnp3py/commit/57aedf5c5cce00b67bcfb393d1f6690e74fb83f9))

- **master**: Screen solicited fragments out before listen_unsolicited parses them
  ([#57](https://github.com/craigpnnl/dnp3py/pull/57),
  [`861d91c`](https://github.com/craigpnnl/dnp3py/commit/861d91c4fef9c8f6d8e26c5e1ad3906521f338c3))

- **master**: Treat peer EOF as a dead link and close the runner
  ([#57](https://github.com/craigpnnl/dnp3py/pull/57),
  [`6be9d90`](https://github.com/craigpnnl/dnp3py/commit/6be9d905831520943da9a8d3a7c901fefae6ee75))

- **master**: Wake a channel's own pending read when it closes
  ([#57](https://github.com/craigpnnl/dnp3py/pull/57),
  [`4ab2b1d`](https://github.com/craigpnnl/dnp3py/commit/4ab2b1dd260631488625ed4e24288baf4a0e134a))

- **master**: Wrap write failures as LinkError and bound writes
  ([#57](https://github.com/craigpnnl/dnp3py/pull/57),
  [`a4c27de`](https://github.com/craigpnnl/dnp3py/commit/a4c27de4ddc76830d93e235959171e50b84160b2))

- **mesa**: Latch binary outputs from the decoded control code
  ([#70](https://github.com/craigpnnl/dnp3py/pull/70),
  [`cba363f`](https://github.com/craigpnnl/dnp3py/commit/cba363f490baa44c6c45e8794db36a30eafd20a8))

- **objects**: Pin every layout row and refuse negative bits per point
  ([#74](https://github.com/craigpnnl/dnp3py/pull/74),
  [`c6498fd`](https://github.com/craigpnnl/dnp3py/commit/c6498fd23839dfe9c90befb6b2ce9e7492327e0c))

- **outstation**: A fully refused SELECT also keeps its response for a retry
  ([#130](https://github.com/craigpnnl/dnp3py/pull/130),
  [`5eb5a9b`](https://github.com/craigpnnl/dnp3py/commit/5eb5a9bcaae3269fdc89c34b12e27f758bfeaf96))

- **outstation**: A partly refused SELECT keeps its response for a retry
  ([#130](https://github.com/craigpnnl/dnp3py/pull/130),
  [`f072df1`](https://github.com/craigpnnl/dnp3py/commit/f072df12727c595eee5d6e687dc7198993c2eb56))

- **outstation**: A SELECT with any non-zero status arms nothing
  ([#130](https://github.com/craigpnnl/dnp3py/pull/130),
  [`3fb52a8`](https://github.com/craigpnnl/dnp3py/commit/3fb52a8dc8dbfd0ae72185cff40847522e8dceb8))

- **outstation**: Accept IMMEDIATE_FREEZE_NO_ACK and FREEZE_CLEAR_NO_ACK
  ([#121](https://github.com/craigpnnl/dnp3py/pull/121),
  [`06605df`](https://github.com/craigpnnl/dnp3py/commit/06605df083d57997d3172e510ba604c2e7e3f37b))

- **outstation**: Apply the Table 4-9 select and operate sequence rules
  ([#72](https://github.com/craigpnnl/dnp3py/pull/72),
  [`ce26047`](https://github.com/craigpnnl/dnp3py/commit/ce260476639a43712f5df696c8ebb12f2e026aa9))

- **outstation**: Check every control block before any point runs
  ([#130](https://github.com/craigpnnl/dnp3py/pull/130),
  [`e3c3317`](https://github.com/craigpnnl/dnp3py/commit/e3c3317219780b2609e5858f6765b09511f9e8c7))

- **outstation**: Cite the precise IEEE 1815-2012 subclauses
  ([#122](https://github.com/craigpnnl/dnp3py/pull/122),
  [`15d61ca`](https://github.com/craigpnnl/dnp3py/commit/15d61caeaaf5e5baaf80f10de2779283a204afa8))

- **outstation**: Close the connection even if releasing its selections fails
  ([#72](https://github.com/craigpnnl/dnp3py/pull/72),
  [`ae1206b`](https://github.com/craigpnnl/dnp3py/commit/ae1206b32bf4b556878a63dd06358bdd21bffab3))

- **outstation**: Correct CON citation, cover empty response CON
  ([#77](https://github.com/craigpnnl/dnp3py/pull/77),
  [`175dc71`](https://github.com/craigpnnl/dnp3py/commit/175dc71067b3100577b907d92797a7ba8db18b3b))

- **outstation**: Decode the whole g12v1 control-code octet
  ([#70](https://github.com/craigpnnl/dnp3py/pull/70),
  [`ab0fefe`](https://github.com/craigpnnl/dnp3py/commit/ab0fefeb634225a19d3f6022ae705a1e0dcafb58))

- **outstation**: Drop analog output parse checks the control gate makes unreachable
  ([#130](https://github.com/craigpnnl/dnp3py/pull/130),
  [`bdefc5f`](https://github.com/craigpnnl/dnp3py/commit/bdefc5f9b3a9baf2eb7fc62237c16932890aed61))

- **outstation**: Drop internal-only references from status-tracking comments
  ([#122](https://github.com/craigpnnl/dnp3py/pull/122),
  [`1274bbb`](https://github.com/craigpnnl/dnp3py/commit/1274bbb26d38cfbce06c7abb3b707767e27e3298))

- **outstation**: Echo each control object's own status
  ([#130](https://github.com/craigpnnl/dnp3py/pull/130),
  [`164e331`](https://github.com/craigpnnl/dnp3py/commit/164e33163d05abf313c51905dc7ad5fee5dd06aa))

- **outstation**: End the selection even when the handler raises during OPERATE
  ([#72](https://github.com/craigpnnl/dnp3py/pull/72),
  [`5623bb6`](https://github.com/craigpnnl/dnp3py/commit/5623bb6985490c08da7470197bf10876f0d888c4))

- **outstation**: End the selection on a request that fails to parse
  ([#72](https://github.com/craigpnnl/dnp3py/pull/72),
  [`849b4d2`](https://github.com/craigpnnl/dnp3py/commit/849b4d2b1223e0177584a5ab1ab72be8fbcf6dd1))

- **outstation**: End the selection when the handler raises during SELECT
  ([#72](https://github.com/craigpnnl/dnp3py/pull/72),
  [`326d630`](https://github.com/craigpnnl/dnp3py/commit/326d630675a2a63afd6a2c4a0989a5398f7f01d1))

- **outstation**: Guard the except-Exception branches and always stop
  ([`7ae8ca4`](https://github.com/craigpnnl/dnp3py/commit/7ae8ca4ce590b0da1f8f30c22a1ba923275376e5))

- **outstation**: Harden the WRITE time_handler contract
  ([#140](https://github.com/craigpnnl/dnp3py/pull/140),
  [`55e34fb`](https://github.com/craigpnnl/dnp3py/commit/55e34fb63d737887652af6d13514c16608e9f18e))

- **outstation**: Isolate SELECT and OPERATE between peers
  ([#72](https://github.com/craigpnnl/dnp3py/pull/72),
  [`8cdc275`](https://github.com/craigpnnl/dnp3py/commit/8cdc275e97f55ff50eafa68549b8343484370f63))

- **outstation**: Key SELECT state by peer and point index
  ([#72](https://github.com/craigpnnl/dnp3py/pull/72),
  [`cf347c0`](https://github.com/craigpnnl/dnp3py/commit/cf347c0529e29ea45f395770dc14a5fcc499f6c4))

- **outstation**: Key the RECORD_CURRENT_TIME instant per peer and bound g50v3 to 48 bits
  ([#142](https://github.com/craigpnnl/dnp3py/pull/142),
  [`7c449be`](https://github.com/craigpnnl/dnp3py/commit/7c449bec7ee2312d41ea019636424bcaa490c140))

- **outstation**: Number connections per outstation, not per runner
  ([#72](https://github.com/craigpnnl/dnp3py/pull/72),
  [`1c32712`](https://github.com/craigpnnl/dnp3py/commit/1c32712acbe97814084248ac64ecb3f1e0361688))

- **outstation**: Propagate a cancellation directed at run()
  ([#68](https://github.com/craigpnnl/dnp3py/pull/68),
  [`8bd4adf`](https://github.com/craigpnnl/dnp3py/commit/8bd4adfaa21c2bf51694594e911cf9371dc4eb58))

- **outstation**: Purge expired selections before a SELECT
  ([#72](https://github.com/craigpnnl/dnp3py/pull/72),
  [`f533022`](https://github.com/craigpnnl/dnp3py/commit/f5330222cc5cf0d91c262b80144b59b66bff583e))

- **outstation**: Read the clock once per g50v3 WRITE block
  ([#142](https://github.com/craigpnnl/dnp3py/pull/142),
  [`83fd4f3`](https://github.com/craigpnnl/dnp3py/commit/83fd4f30a28df5a1272fbc4b4b1caa3580315591))

- **outstation**: Refuse an unframed request of every function the dispatch table runs
  ([#130](https://github.com/craigpnnl/dnp3py/pull/130),
  [`c25589b`](https://github.com/craigpnnl/dnp3py/commit/c25589be51764b9696503a1cbe826f089c1fea82))

- **outstation**: Reject a non-int analog output static variation
  ([#122](https://github.com/craigpnnl/dnp3py/pull/122),
  [`8b74308`](https://github.com/craigpnnl/dnp3py/commit/8b74308c257ca5d8757298cc8711b0b63fd40d6d))

- **outstation**: Release a connection's selections when it closes
  ([#72](https://github.com/craigpnnl/dnp3py/pull/72),
  [`7dd011a`](https://github.com/craigpnnl/dnp3py/commit/7dd011a07d7d3a808f817717c2180b5f876e712f))

- **outstation**: Select and operate analog outputs
  ([#124](https://github.com/craigpnnl/dnp3py/pull/124),
  [`6d46ea6`](https://github.com/craigpnnl/dnp3py/commit/6d46ea60dd694fc0bad697fae183bbcb49d90d93))

- **outstation**: Stamp every point of a selection with its start time in the store
  ([#72](https://github.com/craigpnnl/dnp3py/pull/72),
  [`f2932f3`](https://github.com/craigpnnl/dnp3py/commit/f2932f327f9934b627b9ab823e1a75b4abae40a4))

- **outstation**: State peer-identity comments plainly
  ([#72](https://github.com/craigpnnl/dnp3py/pull/72),
  [`c2572c9`](https://github.com/craigpnnl/dnp3py/commit/c2572c9e473fddb5834ac0987ff845db04d56f33))

- **outstation**: Stop DELAY_MEASURE from clearing NEED_TIME
  ([#140](https://github.com/craigpnnl/dnp3py/pull/140),
  [`d18ea47`](https://github.com/craigpnnl/dnp3py/commit/d18ea47f87f34500fb682601fb5ba8e1694cb914))

- **parser**: Frame every request object block and refuse what cannot be framed
  ([#130](https://github.com/craigpnnl/dnp3py/pull/130),
  [`664c0aa`](https://github.com/craigpnnl/dnp3py/commit/664c0aa0878f264d02c1adc6f824cc2e1649dac6))

- **parser**: Refuse a start-stop range that names no object
  ([#74](https://github.com/craigpnnl/dnp3py/pull/74),
  [`9f0a379`](https://github.com/craigpnnl/dnp3py/commit/9f0a37957199dc344952c44f671a1475f1e8afbc))

- **parser**: Report a reserved range code as a reserved qualifier
  ([#71](https://github.com/craigpnnl/dnp3py/pull/71),
  [`f15edb1`](https://github.com/craigpnnl/dnp3py/commit/f15edb1d2a866e537c4896c0a52f6dc715406578))

- **parser**: Stop at a block it cannot frame and report why
  ([#71](https://github.com/craigpnnl/dnp3py/pull/71),
  [`e6fd965`](https://github.com/craigpnnl/dnp3py/commit/e6fd9658bd27c2f22ac6f386e06d53001f8f4b0c))

- **parser**: Stop at a negative registered object size
  ([#71](https://github.com/craigpnnl/dnp3py/pull/71),
  [`b255fef`](https://github.com/craigpnnl/dnp3py/commit/b255fef50f90b3be0e840a88d5a7414ca07bcdf3))

- **readme**: Make the Quick Start examples run and the protocol tables accurate
  ([#139](https://github.com/craigpnnl/dnp3py/pull/139),
  [`a5925d9`](https://github.com/craigpnnl/dnp3py/commit/a5925d9dcde50f9090f7d75df3bc02c70fa0a139))

- **transport_io**: Bound TcpClientChannel.close and abort a stalled peer
  ([#57](https://github.com/craigpnnl/dnp3py/pull/57),
  [`dc76ee7`](https://github.com/craigpnnl/dnp3py/commit/dc76ee765a5ad637464025d63c5a7c295a042d84))

- **transport_io**: Bound TcpServerChannel.close() and stop()
  ([#85](https://github.com/craigpnnl/dnp3py/pull/85),
  [`1208e59`](https://github.com/craigpnnl/dnp3py/commit/1208e599f4af0ea345b4c3141eafb52df36ffe3c))

- **transport_io**: Close all connections before wait_closed() in stop()
  ([#85](https://github.com/craigpnnl/dnp3py/pull/85),
  [`333ac0a`](https://github.com/craigpnnl/dnp3py/commit/333ac0a3a62b81ad3f9a1e3db1266ed6821676a4))

- **transport_io**: Leave no stale EOF in a reopened SimulatorChannel
  ([#57](https://github.com/craigpnnl/dnp3py/pull/57),
  [`f221fd4`](https://github.com/craigpnnl/dnp3py/commit/f221fd4eb5d8be9a1911586763ee4738acf0bc4e))

- **transport_io**: Propagate close_timeout through serve()
  ([#85](https://github.com/craigpnnl/dnp3py/pull/85),
  [`8c13ab6`](https://github.com/craigpnnl/dnp3py/commit/8c13ab6bb4ddd33268abdb273ec7165552a2fda8))

- **transport_io**: Reach CLOSED after a cancelled close()
  ([#84](https://github.com/craigpnnl/dnp3py/pull/84),
  [`6d9e600`](https://github.com/craigpnnl/dnp3py/commit/6d9e60031fdd7ea4fc9a01ec857c039ae04e5dac))

- **transport_io**: Refuse a connection accepted while not OPEN
  ([#85](https://github.com/craigpnnl/dnp3py/pull/85),
  [`f773ede`](https://github.com/craigpnnl/dnp3py/commit/f773ede565225f0ddce59e5e31b43b62e92589c8))

### Code Style

- **master**: Format the new CON-on-FIN test ([#57](https://github.com/craigpnnl/dnp3py/pull/57),
  [`28695e5`](https://github.com/craigpnnl/dnp3py/commit/28695e595effeb0591eed0a1b54e61d81a66280f))

- **master**: Quote only the forward reference in the delivery annotations
  ([#74](https://github.com/craigpnnl/dnp3py/pull/74),
  [`7e851be`](https://github.com/craigpnnl/dnp3py/commit/7e851be1e980a48f9745b10010caa0357af254ca))

- **master**: Replace em dash with hyphen in comments
  ([`2f8d0e7`](https://github.com/craigpnnl/dnp3py/commit/2f8d0e72b374e3bcaa5fa3d46a93e8801aaa54e8))

### Documentation

- Record ADR-0004, MasterTcpRunner narrow API shape
  ([`914397f`](https://github.com/craigpnnl/dnp3py/commit/914397f676a4454cdb18dc4df3be76b01f74b3a6))

- **core**: Cite the double-bit state and flag clauses correctly
  ([#76](https://github.com/craigpnnl/dnp3py/pull/76),
  [`d3de95e`](https://github.com/craigpnnl/dnp3py/commit/d3de95eded9d091af5a64bab15ad70e8399ec09f))

- **master**: Cite the fragment rule behind the CTO scope
  ([#81](https://github.com/craigpnnl/dnp3py/pull/81),
  [`18e74f4`](https://github.com/craigpnnl/dnp3py/commit/18e74f40c187e6aa43c24c9224979c20b47c15df))

- **master**: Describe a delivery batch as one run of blocks
  ([`988f5d3`](https://github.com/craigpnnl/dnp3py/commit/988f5d3b1d1102aa7127884022b887728d83ab7a))

- **master**: List every kind the delivery table leaves out
  ([#76](https://github.com/craigpnnl/dnp3py/pull/76),
  [`0270f5f`](https://github.com/craigpnnl/dnp3py/commit/0270f5fcb14a094749d433a2869443d161b81e45))

- **master**: Note frozen counter time skips decoding
  ([#79](https://github.com/craigpnnl/dnp3py/pull/79),
  [`2e63cd3`](https://github.com/craigpnnl/dnp3py/commit/2e63cd3ebca868d0eb179d42f9c0b45b4b58fa3d))

- **master**: Say a handler callback can run once per run of blocks
  ([`34f7f30`](https://github.com/craigpnnl/dnp3py/commit/34f7f30b72be0984bcd1fa3c9c85bf11fe4fc0a5))

- **master**: Say plainly when the packed decoders return nothing
  ([#103](https://github.com/craigpnnl/dnp3py/pull/103),
  [`cb728ba`](https://github.com/craigpnnl/dnp3py/commit/cb728bafc67ddc3575a6e20b8a4990d260e0b7d2))

- **master**: Say why the packed double-bit count check stays
  ([#76](https://github.com/craigpnnl/dnp3py/pull/76),
  [`4422ee1`](https://github.com/craigpnnl/dnp3py/commit/4422ee1295577d73aa875f4ad1e705b475f558f5))

- **master**: State when a handler receives no double-bit values
  ([#76](https://github.com/craigpnnl/dnp3py/pull/76),
  [`213b7f1`](https://github.com/craigpnnl/dnp3py/commit/213b7f1f476352b4b17d8f91db958845d7da6ee2))

- **mesa-outstation**: Correct the stale CLI help text
  ([#139](https://github.com/craigpnnl/dnp3py/pull/139),
  [`4129790`](https://github.com/craigpnnl/dnp3py/commit/412979098440d6cac5eccd19b1e0c0edeb7a81d3))

- **objects**: Correct the g21 A.11 comment against the clauses
  ([#80](https://github.com/craigpnnl/dnp3py/pull/80),
  [`9c46f95`](https://github.com/craigpnnl/dnp3py/commit/9c46f95d5afba11c1c3ce53b4b076f2738f7c035))

- **objects**: Note why g33v8 uses FLT64 despite A.17.8's printed FLT32
  ([#74](https://github.com/craigpnnl/dnp3py/pull/74),
  [`83bb14f`](https://github.com/craigpnnl/dnp3py/commit/83bb14f742154468d9c0d7247458017f7701572c))

- **objects**: Stop claiming g23 delta variations share the flag field
  ([#74](https://github.com/craigpnnl/dnp3py/pull/74),
  [`509a520`](https://github.com/craigpnnl/dnp3py/commit/509a5209223572c233a7ffd57820c0d05e8e9ff1))

- **outstation**: Cite the profile tables by their real numbers
  ([#140](https://github.com/craigpnnl/dnp3py/pull/140),
  [`4031380`](https://github.com/craigpnnl/dnp3py/commit/40313808181704d86171d87bbf2068f36c0b625b))

- **outstation**: Correct the g80v1 and Rule W WRITE clause citations
  ([#140](https://github.com/craigpnnl/dnp3py/pull/140),
  [`afb8d6d`](https://github.com/craigpnnl/dnp3py/commit/afb8d6dd7072bbade5870d452a1fdc3574fd9a98))

- **outstation**: Name the shared analog output parser in comments
  ([#124](https://github.com/craigpnnl/dnp3py/pull/124),
  [`8171568`](https://github.com/craigpnnl/dnp3py/commit/8171568286cc46e8bf486e5d851019073da692d0))

- **outstation**: State that handlers receive the whole control-code octet
  ([#70](https://github.com/craigpnnl/dnp3py/pull/70),
  [`3063b33`](https://github.com/craigpnnl/dnp3py/commit/3063b33fb2b709e2ef226dcf4d0b1ef995da41a6))

- **readme**: Configure logging in the Outstation quick start block
  ([#139](https://github.com/craigpnnl/dnp3py/pull/139),
  [`75eb2ae`](https://github.com/craigpnnl/dnp3py/commit/75eb2ae595fd62cc56a3818dff503be8a7569e83))

- **readme**: Describe DELAY_MEASURE as the outstation's own processing delay
  ([#142](https://github.com/craigpnnl/dnp3py/pull/142),
  [`5f36923`](https://github.com/craigpnnl/dnp3py/commit/5f3692376c8f2b4f502c50d13ba107a396ea8327))

- **readme**: Describe LAN time sync as implemented
  ([#142](https://github.com/craigpnnl/dnp3py/pull/142),
  [`71831b3`](https://github.com/craigpnnl/dnp3py/commit/71831b3f48b455838b09dbd91200224d4d16702f))

- **readme**: State what the Level 2 gap actually does today
  ([#139](https://github.com/craigpnnl/dnp3py/pull/139),
  [`c496abc`](https://github.com/craigpnnl/dnp3py/commit/c496abcaf3b02f2a8af0f9a394e6c39196cc9f0f))

### Features

- Add MasterTcpRunner, a TCP driver for the master role
  ([`be350a2`](https://github.com/craigpnnl/dnp3py/commit/be350a2224c9fcffde5026fd365234b6467479eb))

- **core**: Export OperationType and TripCloseCode from dnp3.core
  ([#70](https://github.com/craigpnnl/dnp3py/pull/70),
  [`dbae3bc`](https://github.com/craigpnnl/dnp3py/commit/dbae3bc06ea3a8ecbd5292b7ee173fc9a9b26939))

- **database**: Add analog output points ([#122](https://github.com/craigpnnl/dnp3py/pull/122),
  [`57de5bd`](https://github.com/craigpnnl/dnp3py/commit/57de5bd0e1f076dda5a6c4c178fa45e861f315c3))

- **database**: Give event buffer entries serials, read and remove by serial
  ([#77](https://github.com/craigpnnl/dnp3py/pull/77),
  [`aad9b32`](https://github.com/craigpnnl/dnp3py/commit/aad9b3287f752904f6fa2551acb475813a1b52bf))

- **master**: Add DefaultSOEHandler.get_double_bit_input
  ([#76](https://github.com/craigpnnl/dnp3py/pull/76),
  [`3649559`](https://github.com/craigpnnl/dnp3py/commit/3649559222d515a4784947ebe747f442945e4e4c))

- **master**: Decode absolute event timestamps in the shared decode path
  ([#81](https://github.com/craigpnnl/dnp3py/pull/81),
  [`410e995`](https://github.com/craigpnnl/dnp3py/commit/410e99524ad5305f6bc37d94cc942542e29e7d4c))

- **master**: Decode and deliver double-bit binary inputs and events
  ([#76](https://github.com/craigpnnl/dnp3py/pull/76),
  [`f5ced43`](https://github.com/craigpnnl/dnp3py/commit/f5ced4328465b29f1e20048e6174ad87e975b48f))

- **master**: Report a truncated response in ResponseInfo
  ([#103](https://github.com/craigpnnl/dnp3py/pull/103),
  [`e11fc88`](https://github.com/craigpnnl/dnp3py/commit/e11fc88a47fc174100a6b2503eecec8f94ec276a))

- **master**: Time relative events from the common time of occurrence
  ([#81](https://github.com/craigpnnl/dnp3py/pull/81),
  [`95689c7`](https://github.com/craigpnnl/dnp3py/commit/95689c769d1efc8d8b03f278644e90d547484d3a))

- **objects**: Add a wire-layout table checked against the registry
  ([#74](https://github.com/craigpnnl/dnp3py/pull/74),
  [`7e98884`](https://github.com/craigpnnl/dnp3py/commit/7e988848efb1841c99f5e3c715571e9bc5518010))

- **objects**: Add analog output status and event layouts
  ([#74](https://github.com/craigpnnl/dnp3py/pull/74),
  [`43559fc`](https://github.com/craigpnnl/dnp3py/commit/43559fcad925012f107cc08faa2e77c873f187db))

- **objects**: Add layout rows for g20/g21/g22 delta and without-flag variations
  ([#80](https://github.com/craigpnnl/dnp3py/pull/80),
  [`a6a0689`](https://github.com/craigpnnl/dnp3py/commit/a6a0689e3303c986f31b01352d7d7ae586e3b7fb))

- **objects**: Add layout rows for g3v2, g4, g13, g31, g33, g34, g41, g43
  ([#74](https://github.com/craigpnnl/dnp3py/pull/74),
  [`fcc9277`](https://github.com/craigpnnl/dnp3py/commit/fcc9277f1e0e1f9d1078223b22495ff0376b7a06))

- **objects**: Add wire-layout rows for group 23 frozen counter events
  ([#74](https://github.com/craigpnnl/dnp3py/pull/74),
  [`829d1c2`](https://github.com/craigpnnl/dnp3py/commit/829d1c2e8b4f831a76fbb7a9bf572cc17f9bb83c))

- **outstation**: Accept a WRITE of g50v1 and check every WRITE block first
  ([#140](https://github.com/craigpnnl/dnp3py/pull/140),
  [`023932d`](https://github.com/craigpnnl/dnp3py/commit/023932d4e38feaf0fd6ea56e1855244172cc8766))

- **outstation**: Add PeerId peer-identity type ([#72](https://github.com/craigpnnl/dnp3py/pull/72),
  [`a9710ef`](https://github.com/craigpnnl/dnp3py/commit/a9710efa2d8873edb9339c41a6a88598c57b1ef9))

- **outstation**: Assign per-connection peer ids in the TCP runner
  ([#72](https://github.com/craigpnnl/dnp3py/pull/72),
  [`1f0ab98`](https://github.com/craigpnnl/dnp3py/commit/1f0ab988cde6b73908eeeab71b076be2ff562e16))

- **outstation**: Builders accept con; unsolicited responses set it
  ([#77](https://github.com/craigpnnl/dnp3py/pull/77),
  [`d4ba2d1`](https://github.com/craigpnnl/dnp3py/commit/d4ba2d1f84b3385f0bc7927c632a954732b0ab86))

- **outstation**: Serve group 40 analog output status on READ and Class 0
  ([#122](https://github.com/craigpnnl/dnp3py/pull/122),
  [`e37213f`](https://github.com/craigpnnl/dnp3py/commit/e37213f534d33e756de0be04f73e223537153dd1))

- **outstation**: Support RECORD_CURRENT_TIME and WRITE of g50v3
  ([#142](https://github.com/craigpnnl/dnp3py/pull/142),
  [`e2c2ac7`](https://github.com/craigpnnl/dnp3py/commit/e2c2ac78631ccfdbedb36330ba24fb3d38dbea41))

- **outstation**: Thread peer identity through process_request
  ([#72](https://github.com/craigpnnl/dnp3py/pull/72),
  [`f2bc657`](https://github.com/craigpnnl/dnp3py/commit/f2bc6575dd587b4112a9ae408394e8a673ba7b1c))

- **outstation**: Update analog output status after a successful g41 command
  ([#122](https://github.com/craigpnnl/dnp3py/pull/122),
  [`c01d353`](https://github.com/craigpnnl/dnp3py/commit/c01d3538d10cf378da9f7c9752a95b3160ad409d))

- **parser**: Frame response blocks from the wire-layout table
  ([#74](https://github.com/craigpnnl/dnp3py/pull/74),
  [`2a2a9dc`](https://github.com/craigpnnl/dnp3py/commit/2a2a9dcda01ae56ff4ccf330b456698a2c1dcf6a))

### Refactoring

- **master**: Decode values from the wire-layout table
  ([#74](https://github.com/craigpnnl/dnp3py/pull/74),
  [`5f7fedb`](https://github.com/craigpnnl/dnp3py/commit/5f7fedbc2b2897ba5adb52ca56baf556bda9c67e))

- **master**: Drop run_polls from MasterTcpRunner
  ([#57](https://github.com/craigpnnl/dnp3py/pull/57),
  [`c28c236`](https://github.com/craigpnnl/dnp3py/commit/c28c23658215ea5864d3d5108e8839d9885e0322))

- **master**: Drop the per-kind parse methods and unused group constants
  ([#74](https://github.com/craigpnnl/dnp3py/pull/74),
  [`5029d3a`](https://github.com/craigpnnl/dnp3py/commit/5029d3aeb789d190c8d9257b4b3adbc723ce82bd))

- **outstation**: Keep one selection record per peer
  ([#72](https://github.com/craigpnnl/dnp3py/pull/72),
  [`675e94f`](https://github.com/craigpnnl/dnp3py/commit/675e94fef04248c9dac8f3dd79ecd5caef829463))

- **outstation**: Parse analog output blocks in one helper
  ([#124](https://github.com/craigpnnl/dnp3py/pull/124),
  [`a45e334`](https://github.com/craigpnnl/dnp3py/commit/a45e334f6c06fa70121675fd2a2426bb10f1d8cc))

- **parser**: State what each truncation reason means
  ([#71](https://github.com/craigpnnl/dnp3py/pull/71),
  [`8a27fb6`](https://github.com/craigpnnl/dnp3py/commit/8a27fb6aae9678fc6b1baef33aa3a09c51b812aa))

- **tests**: Drop internal review-round references from g50v3 test docstrings
  ([#142](https://github.com/craigpnnl/dnp3py/pull/142),
  [`2e52683`](https://github.com/craigpnnl/dnp3py/commit/2e52683480097336e3fce9a16ac398454482e4fb))

- **transport-io**: Move close_timeout onto TcpConfig; abort on cancelled close
  ([#57](https://github.com/craigpnnl/dnp3py/pull/57),
  [`3ba503e`](https://github.com/craigpnnl/dnp3py/commit/3ba503ef1ca03c91973fbc90144945d4106de6ce))

### Testing

- **database**: Close event-serial coverage gaps from review
  ([#77](https://github.com/craigpnnl/dnp3py/pull/77),
  [`90d3859`](https://github.com/craigpnnl/dnp3py/commit/90d38593ec007a310915170c7b3095856b38eef2))

- **database**: Pin analog output acceptance of infinity
  ([#122](https://github.com/craigpnnl/dnp3py/pull/122),
  [`a203cb1`](https://github.com/craigpnnl/dnp3py/commit/a203cb189da5a699c53fe292eca0272f9e1b0f13))

- **master**: Assert frozen counter event values for every g23 variation
  ([#74](https://github.com/craigpnnl/dnp3py/pull/74),
  [`b497eb9`](https://github.com/craigpnnl/dnp3py/commit/b497eb9b3109565322596d7b20ea3776388b06aa))

- **master**: Assert the g30v1 value in the g21v9 block-ahead test
  ([#80](https://github.com/craigpnnl/dnp3py/pull/80),
  [`cf0e792`](https://github.com/craigpnnl/dnp3py/commit/cf0e7924c0da5040835276bff3a24796ac60ba8a))

- **master**: Close three timestamp coverage gaps found in review
  ([#81](https://github.com/craigpnnl/dnp3py/pull/81),
  [`0d120b9`](https://github.com/craigpnnl/dnp3py/commit/0d120b92e887b92bb0b5807cc38c7304a43207aa))

- **master**: Confirm a solicited final fragment that sets CON
  ([#57](https://github.com/craigpnnl/dnp3py/pull/57),
  [`ff65716`](https://github.com/craigpnnl/dnp3py/commit/ff657162091164211219f7643de3c97a9e0ae17d))

- **master**: Correct a stale quality comment on g20v7
  ([#80](https://github.com/craigpnnl/dnp3py/pull/80),
  [`6ea6500`](https://github.com/craigpnnl/dnp3py/commit/6ea65008664785f123fe59916bc0935cd677568c))

- **master**: Correct two comments on the undelivered new kinds
  ([#74](https://github.com/craigpnnl/dnp3py/pull/74),
  [`cb11390`](https://github.com/craigpnnl/dnp3py/commit/cb11390301691e9797987da167add9b0e522397d))

- **master**: Cover a count qualifier with a top-bit-set count for g23v5
  ([#74](https://github.com/craigpnnl/dnp3py/pull/74),
  [`c030063`](https://github.com/craigpnnl/dnp3py/commit/c030063ea2c74bf972de88d300d31e744f3a7835))

- **master**: Cover a count qualifier with an index prefix for g20v1
  ([#80](https://github.com/craigpnnl/dnp3py/pull/80),
  [`712a73a`](https://github.com/craigpnnl/dnp3py/commit/712a73a7f1e21fbe85b6c45262968dbd9e1009f3))

- **master**: Cover a g3v1 block shorter than its declared range
  ([#76](https://github.com/craigpnnl/dnp3py/pull/76),
  [`f54e525`](https://github.com/craigpnnl/dnp3py/commit/f54e525acc5e6c5bed390d4256eb75246972239c))

- **master**: Cover point-kind routing and analog output decoding
  ([#74](https://github.com/craigpnnl/dnp3py/pull/74),
  [`b7b3724`](https://github.com/craigpnnl/dnp3py/commit/b7b37242cd5f0043712dc99ef3b384f258852649))

- **master**: Decode non-zero flags, values and time in every layout row
  ([#74](https://github.com/craigpnnl/dnp3py/pull/74),
  [`c625578`](https://github.com/craigpnnl/dnp3py/commit/c62557808dd8e0d86c2e5239606861fa708f5e61))

- **master**: Deliver g20/g21/g22 missing counter variations
  ([#80](https://github.com/craigpnnl/dnp3py/pull/80),
  [`f6432ee`](https://github.com/craigpnnl/dnp3py/commit/f6432eec9876e77812c42227c746eeb6b90e8bc3))

- **master**: Deliver the block after a g1v1 or g40 block
  ([#74](https://github.com/craigpnnl/dnp3py/pull/74),
  [`47f090b`](https://github.com/craigpnnl/dnp3py/commit/47f090b591f96e5b08ffd7a224315b794f6f62de))

- **master**: Exercise g21v5/v6 two-object stride and quality
  ([#79](https://github.com/craigpnnl/dnp3py/pull/79),
  [`707b031`](https://github.com/craigpnnl/dnp3py/commit/707b031d40053466aadf3d57d46fb6431cc173b9))

- **master**: Expect no values from a short trailing double-bit block
  ([#114](https://github.com/craigpnnl/dnp3py/pull/114),
  [`8d80fd4`](https://github.com/craigpnnl/dnp3py/commit/8d80fd4a9a73a96f4710d7aa06a3749e1c9701d9))

- **master**: Pin that a truncated fragment is confirmed and returned
  ([#103](https://github.com/craigpnnl/dnp3py/pull/103),
  [`acf89f7`](https://github.com/craigpnnl/dnp3py/commit/acf89f70458076618e0a49fa11cc8d93fcd260a7))

- **master**: Pin the delivery table and check blocks ahead of g30v1
  ([#74](https://github.com/craigpnnl/dnp3py/pull/74),
  [`aa64d9f`](https://github.com/craigpnnl/dnp3py/commit/aa64d9fa8eb485369d34d47809bc16da2ad7acaf))

- **master**: Pin the round-up in the packed double-bit length check
  ([#103](https://github.com/craigpnnl/dnp3py/pull/103),
  [`2e24f2e`](https://github.com/craigpnnl/dnp3py/commit/2e24f2e36ca752838081a519a42b83841f77e707))

- **master**: Pin trailing octets through process_response
  ([#103](https://github.com/craigpnnl/dnp3py/pull/103),
  [`42d344f`](https://github.com/craigpnnl/dnp3py/commit/42d344fb8346eb33fee094cbb2477f60e782b10a))

- **master**: Pin what ends a run of delivered blocks
  ([`a09e4ac`](https://github.com/craigpnnl/dnp3py/commit/a09e4ac0e409298fa3fa7eed2c9ef68c44e5244a))

- **master**: Pin where the double-bit callback runs among the others
  ([#76](https://github.com/craigpnnl/dnp3py/pull/76),
  [`b532c3e`](https://github.com/craigpnnl/dnp3py/commit/b532c3e3560a90fa09c29218edbb465e4d033bfd))

- **master**: Pin which common time of occurrence survives an odd g51 block
  ([#81](https://github.com/craigpnnl/dnp3py/pull/81),
  [`3580e8c`](https://github.com/craigpnnl/dnp3py/commit/3580e8c2f2708e3fa92093a420bf90ea0deceb8f))

- **master**: Pin wire order for several runs before a truncation
  ([#81](https://github.com/craigpnnl/dnp3py/pull/81),
  [`2795ff0`](https://github.com/craigpnnl/dnp3py/commit/2795ff0dbf53cf0abc03a9669c7c24fb22d09a8e))

- **master**: Prove new group/variation pairs frame but do not deliver
  ([#74](https://github.com/craigpnnl/dnp3py/pull/74),
  [`91f92b4`](https://github.com/craigpnnl/dnp3py/commit/91f92b48677c9a36ce3001fa8a4a5c6f68d2420a))

- **master**: Share the decode recorder and pin that g11v3 delivers nothing
  ([#74](https://github.com/craigpnnl/dnp3py/pull/74),
  [`fd4aabc`](https://github.com/craigpnnl/dnp3py/commit/fd4aabc3a6615487610909980808a225b761d2ec))

- **master**: State where the EX 4-9 expected values come from
  ([#74](https://github.com/craigpnnl/dnp3py/pull/74),
  [`98ab69d`](https://github.com/craigpnnl/dnp3py/commit/98ab69d48a7fe37bd4024efb0ec2ad92541a9b18))

- **master**: Stop pinning a coincidental None on absolute-time canaries
  ([#81](https://github.com/craigpnnl/dnp3py/pull/81),
  [`94b327c`](https://github.com/craigpnnl/dnp3py/commit/94b327ca574661dd31363f5184a4d3fa55925e77))

- **master**: Tighten failed-open assertions for owned and injected channels
  ([#57](https://github.com/craigpnnl/dnp3py/pull/57),
  [`40bcd3c`](https://github.com/craigpnnl/dnp3py/commit/40bcd3cb1ea075876c7417a91befe06a00f25b7a))

- **master**: Type the slow handler in the spent-deadline test
  ([#57](https://github.com/craigpnnl/dnp3py/pull/57),
  [`5bbda26`](https://github.com/craigpnnl/dnp3py/commit/5bbda2628ddfc2159f7fdc527c8afc8a11798027))

- **master**: Use analog deadband for the undelivered dispatch cases
  ([#76](https://github.com/craigpnnl/dnp3py/pull/76),
  [`0743612`](https://github.com/craigpnnl/dnp3py/commit/0743612940562f16b3bac965491e140ba68a65a1))

- **mesa**: Pin Trip-Close combinations other than PULSE_ON as not supported
  ([#70](https://github.com/craigpnnl/dnp3py/pull/70),
  [`3c91f73`](https://github.com/craigpnnl/dnp3py/commit/3c91f73688e1bc4c107af6cabee39d550e5792e8))

- **objects**: Add the g50v3 wire layout row for LAN time sync
  ([#142](https://github.com/craigpnnl/dnp3py/pull/142),
  [`7c69955`](https://github.com/craigpnnl/dnp3py/commit/7c69955474a0f792bfd5d247cd6546e11fde54cc))

- **outstation**: A partly refused SELECT with no request octets leaves no record
  ([#130](https://github.com/craigpnnl/dnp3py/pull/130),
  [`f4947a2`](https://github.com/craigpnnl/dnp3py/commit/f4947a28eda0533c4012658908ca8cd4d37ba526))

- **outstation**: Assert class 0 serves g40v1 when configured
  ([#122](https://github.com/craigpnnl/dnp3py/pull/122),
  [`6ba6e62`](https://github.com/craigpnnl/dnp3py/commit/6ba6e62ee1dc43bbf1e57893f2e1d1af2a722bb0))

- **outstation**: Assert g40v3 clamp at the float32 boundary
  ([#122](https://github.com/craigpnnl/dnp3py/pull/122),
  [`6ea0e82`](https://github.com/craigpnnl/dnp3py/commit/6ea0e82197da42e07c7a2c4c6ce5eabfcfafb399))

- **outstation**: Assert group 40 analog output status wire bytes
  ([#122](https://github.com/craigpnnl/dnp3py/pull/122),
  [`0bd371f`](https://github.com/craigpnnl/dnp3py/commit/0bd371f52f44fae666300c92bd246cd924bcb1f5))

- **outstation**: Assert master receives clamped g40v2 with OVER_RANGE
  ([#122](https://github.com/craigpnnl/dnp3py/pull/122),
  [`0ca3804`](https://github.com/craigpnnl/dnp3py/commit/0ca3804a78dad1d46a529205619543a583fe738c))

- **outstation**: Close peer-identity coverage gaps for #72
  ([`d63b87b`](https://github.com/craigpnnl/dnp3py/commit/d63b87bb631a8e0e48754dc082eee466819a2a21))

- **outstation**: CROB selection against an analog OPERATE of value 0
  ([#124](https://github.com/craigpnnl/dnp3py/pull/124),
  [`b5e4213`](https://github.com/craigpnnl/dnp3py/commit/b5e4213f8cd9c5eac0864bf151dff29d2ba05aed))

- **outstation**: Drop an unused noqa directive ([#72](https://github.com/craigpnnl/dnp3py/pull/72),
  [`a01e0cc`](https://github.com/craigpnnl/dnp3py/commit/a01e0ccfba74ce010651af43c854df6eb064c422))

- **outstation**: Drop item-number prefixes from class docstrings
  ([#142](https://github.com/craigpnnl/dnp3py/pull/142),
  [`f2a82b4`](https://github.com/craigpnnl/dnp3py/commit/f2a82b41747cb073b258a7a62413e2cef54547cb))

- **outstation**: End the selection on WRITE and direct operate as on READ
  ([#72](https://github.com/craigpnnl/dnp3py/pull/72),
  [`3b6b530`](https://github.com/craigpnnl/dnp3py/commit/3b6b5300447354c7c74751180b5cc293ff37d5e7))

- **outstation**: Keep another connection's instant usable after release
  ([#142](https://github.com/craigpnnl/dnp3py/pull/142),
  [`b8ce1be`](https://github.com/craigpnnl/dnp3py/commit/b8ce1bef338d856af0ce86c6e51dfcd8ef66b24b))

- **outstation**: Keep another peer's instant usable after a WRITE
  ([#142](https://github.com/craigpnnl/dnp3py/pull/142),
  [`90c05d7`](https://github.com/craigpnnl/dnp3py/commit/90c05d7072ebbea38449c34d04c2334294bba899))

- **outstation**: Malformed analog output SELECT and OPERATE
  ([#124](https://github.com/craigpnnl/dnp3py/pull/124),
  [`5479e88`](https://github.com/craigpnnl/dnp3py/commit/5479e884680974feb773cf0fd2c858a918ae70f6))

- **outstation**: Name the unknown g41 variation test after the bit it checks
  ([#130](https://github.com/craigpnnl/dnp3py/pull/130),
  [`d854ba3`](https://github.com/craigpnnl/dnp3py/commit/d854ba31aa00e69dae6d99695c3954c68b9ccdbc))

- **outstation**: Pin a SELECT from one source on a second connection
  ([#72](https://github.com/craigpnnl/dnp3py/pull/72),
  [`b90c98b`](https://github.com/craigpnnl/dnp3py/commit/b90c98bda14ef0169dbbe09dc61c7edcf4e381ce))

- **outstation**: Pin a WRITE refusal by bytes, cover a reserved qualifier bit
  ([#140](https://github.com/craigpnnl/dnp3py/pull/140),
  [`1464f22`](https://github.com/craigpnnl/dnp3py/commit/1464f22d464d87fce61a5367803e74a468af3203))

- **outstation**: Pin freeze NO_ACK rejection by the default handler
  ([#121](https://github.com/craigpnnl/dnp3py/pull/121),
  [`cd55352`](https://github.com/craigpnnl/dnp3py/commit/cd5535285e6fb81a996f3adaa9621cfda477258e))

- **outstation**: Pin one selection timer for every selected point
  ([#72](https://github.com/craigpnnl/dnp3py/pull/72),
  [`c2ce9e5`](https://github.com/craigpnnl/dnp3py/commit/c2ce9e5ee39377c396b6f93aa7b69cb0ff6772e3))

- **outstation**: Pin RECORD_CURRENT_TIME bytes and close two g50v3 rounding and refusal gaps
  ([#142](https://github.com/craigpnnl/dnp3py/pull/142),
  [`62f64ab`](https://github.com/craigpnnl/dnp3py/commit/62f64abd6d08dac2dca72ea98f9f7ab9f8d3db44))

- **outstation**: Pin Rule 3 for a format error, Rule 7 order, and g12v2
  ([#130](https://github.com/craigpnnl/dnp3py/pull/130),
  [`320bfab`](https://github.com/craigpnnl/dnp3py/commit/320bfab90be28d3aca819a9fffe0e8941ba94c46))

- **outstation**: Pin run() cancellation propagation at both sites
  ([#68](https://github.com/craigpnnl/dnp3py/pull/68),
  [`d9a38db`](https://github.com/craigpnnl/dnp3py/commit/d9a38db297702f28c1b44bad95529317e725ba99))

- **outstation**: Pin that a mismatched OPERATE disarms the holder
  ([#72](https://github.com/craigpnnl/dnp3py/pull/72),
  [`360c9c1`](https://github.com/craigpnnl/dnp3py/commit/360c9c1278f5b672ad6b4601fa7579b152ccd218))

- **outstation**: Pin the except-Exception cancellation race and the
  ([`b48ca7b`](https://github.com/craigpnnl/dnp3py/commit/b48ca7b5a69cc7c2f326015fc61b41af52908340))

- **outstation**: Pin the refusal IIN2 bit for every reason framing stops
  ([#130](https://github.com/craigpnnl/dnp3py/pull/130),
  [`1a5d497`](https://github.com/craigpnnl/dnp3py/commit/1a5d49714b9b9d6160a6556bccc12a286fb5e1fe))

- **outstation**: Reach the g41 qualifier check with a block that frames
  ([#130](https://github.com/craigpnnl/dnp3py/pull/130),
  [`12ba921`](https://github.com/craigpnnl/dnp3py/commit/12ba921727760e48f44a5f75c1363fca325c19ed))

- **outstation**: Refuse a later unframeable block for every executed function
  ([#130](https://github.com/craigpnnl/dnp3py/pull/130),
  [`7036445`](https://github.com/craigpnnl/dnp3py/commit/7036445ad42e1f080276f544df9ddd706306508f))

- **outstation**: Say what the g41v5 direct operate test checks
  ([#130](https://github.com/craigpnnl/dnp3py/pull/130),
  [`f34b602`](https://github.com/craigpnnl/dnp3py/commit/f34b602ea77c7fd9161f9ff1b56cf9bfac3f3872))

- **outstation**: Sharpen the cancellation-race and logging tests
  ([#68](https://github.com/craigpnnl/dnp3py/pull/68),
  [`50d42f5`](https://github.com/craigpnnl/dnp3py/commit/50d42f593c35b914d348c5a20dde994a61b7f294))

- **outstation**: Stop naming a removed echo helper in docstrings
  ([#130](https://github.com/craigpnnl/dnp3py/pull/130),
  [`c3d7004`](https://github.com/craigpnnl/dnp3py/commit/c3d7004c0c9e839947f4ff9755b31d4175dd5139))

- **outstation**: Update four tests to request block framing
  ([#130](https://github.com/craigpnnl/dnp3py/pull/130),
  [`5e07dac`](https://github.com/craigpnnl/dnp3py/commit/5e07dac9e5b6a2ce02480c06f83e5c859890137d))

- **parser**: Frame a g80v1 response block and deliver the block after it
  ([#130](https://github.com/craigpnnl/dnp3py/pull/130),
  [`52faf70`](https://github.com/craigpnnl/dnp3py/commit/52faf702a14c90d85f3c5cf2e2b20aff01e88a3d))

- **parser**: Pin index-prefixed ranges and a refused WRITE
  ([#130](https://github.com/craigpnnl/dnp3py/pull/130),
  [`6076613`](https://github.com/craigpnnl/dnp3py/commit/60766139ea4f37dff11cffc79cff3d50036fb52d))

- **parser**: Pin short-by-one and all-objects index-prefix framing
  ([#71](https://github.com/craigpnnl/dnp3py/pull/71),
  [`b26fca3`](https://github.com/craigpnnl/dnp3py/commit/b26fca3f78ec96a84bcba419a492f1b6b0fa716e))

- **parser**: Size registry-only objects behind an index prefix
  ([#74](https://github.com/craigpnnl/dnp3py/pull/74),
  [`e5fdc75`](https://github.com/craigpnnl/dnp3py/commit/e5fdc7526becbf45407a043331d46aff1831f13f))

- **readme**: Expect only CancelledError from a bounded shutdown wait
  ([#139](https://github.com/craigpnnl/dnp3py/pull/139),
  [`b68164c`](https://github.com/craigpnnl/dnp3py/commit/b68164c48a70c780193a706fee68af747be2b05f))

- **readme**: Prove the Quick Start examples with an integration test
  ([#139](https://github.com/craigpnnl/dnp3py/pull/139),
  [`e44b379`](https://github.com/craigpnnl/dnp3py/commit/e44b379a5088d9c3c7fa991758a75fd385b8fdc7))

- **readme**: Run the Outstation and Master blocks extracted from README.md
  ([#139](https://github.com/craigpnnl/dnp3py/pull/139),
  [`14f8d1a`](https://github.com/craigpnnl/dnp3py/commit/14f8d1a1f238b86d3e1a4b12e605fa81b645a21a))

- **transport-io**: Assert a stalled or cancelled close aborts the socket
  ([#57](https://github.com/craigpnnl/dnp3py/pull/57),
  [`ffdc1e4`](https://github.com/craigpnnl/dnp3py/commit/ffdc1e40ffe3c9a16f074e69f67df33a9cb3ba58))

- **transport-io**: Catch a stale parked-read count leaking a false EOF
  ([#57](https://github.com/craigpnnl/dnp3py/pull/57),
  [`4266a43`](https://github.com/craigpnnl/dnp3py/commit/4266a43bf951d88f57125afcd22649436cfba03c))

- **transport_io**: Assert cancelled close() reaches CLOSED
  ([#84](https://github.com/craigpnnl/dnp3py/pull/84),
  [`8d772de`](https://github.com/craigpnnl/dnp3py/commit/8d772de5ebaeadc6c31c611c147e496a3e978821))

- **transport_io**: Assert the accept queue stays empty on refusal
  ([#85](https://github.com/craigpnnl/dnp3py/pull/85),
  [`fa565f6`](https://github.com/craigpnnl/dnp3py/commit/fa565f6a668adb2b4dab9cec7b3629c151980eee))

- **transport_io**: Cover SimulatorChannel's own-close wake on a parked read
  ([#57](https://github.com/craigpnnl/dnp3py/pull/57),
  [`25029a4`](https://github.com/craigpnnl/dnp3py/commit/25029a40ab8436c973a0cddf2bd37ceb66683f16))


## v0.4.0 (2026-08-26)

### Bug Fixes

- Correct ResponseInfo fir/fin/con docstring wording
  ([`89842c1`](https://github.com/craigpnnl/dnp3py/commit/89842c1890f5ca1677d76c485d53664fe510f798))

- Increment application sequence per outstation fragment
  ([`fc5dc55`](https://github.com/craigpnnl/dnp3py/commit/fc5dc552d3773db11e5be06b97ac5edd0156ea7d))

- Verify CONFIRM sequence before advancing fragment loop
  ([`1e903ac`](https://github.com/craigpnnl/dnp3py/commit/1e903ac208f82175c11894be8780025b8b68bac8))

- **ci**: Treat any non-success job result as not-success in release outcome
  ([`2d896f5`](https://github.com/craigpnnl/dnp3py/commit/2d896f52633669a64e934ce5c5e2ac9b443d3d7d))

### Features

- Expose fir/fin/con fragment flags on ResponseInfo
  ([`cc35909`](https://github.com/craigpnnl/dnp3py/commit/cc359093161219591f3ecc26f9905c92be56a294))


## v0.3.2 (2026-08-25)

### Bug Fixes

- **release**: Add the changelog insertion_flag marker PSR requires
  ([`05bc2fc`](https://github.com/craigpnnl/dnp3py/commit/05bc2fc6b53ebe5ff62aa2762b36e96c3a0d4050))

- **release**: Drop the deprecated changelog_file key, rely on its default
  ([`5582674`](https://github.com/craigpnnl/dnp3py/commit/55826740feba25e33f42493afb28a2dbbc91cf11))

### Documentation

- Backfill 0.3.0 and 0.3.1 CHANGELOG sections
  ([`5b6d2cf`](https://github.com/craigpnnl/dnp3py/commit/5b6d2cfd7c5a8019d612d2a2e57534bd0674e614))

- **release**: Trim PSR config comments to load-bearing facts
  ([`c8ce68b`](https://github.com/craigpnnl/dnp3py/commit/c8ce68b835a6076c4d5ac260095e8c90a4707f0f))


## [Unreleased]

## [0.3.1] - 2026-08-25

### Fixed

- Master responses carrying more than one object block are no longer
  truncated to the first block. Each block is now delimited by its
  per-object size from the object registry. `parse_object_headers` is
  unchanged and still serves requests, which carry no object data.
- Master value parsers now decode the count qualifiers (`0x17`, `0x28`) that
  every event group uses, together with each object's index prefix.
  Previously the count field and the index prefixes were read as flag and
  value bytes, reporting points at wrong indices with wrong values.
- Bit-packed binary decoding is now selected by object group rather than by
  variation number alone, so binary event blocks (`g2v1`, `g11v1`) are
  decoded as one flags byte per point instead of as packed bits. Packed
  decoding is also bounded by the declared object count, so the unused high
  bits of the final byte are no longer reported as points.
- Master parsing of the float analog variations `g30v5` and `g30v6` no
  longer returns an empty list, and the timestamped event variations
  (`g2v2`, `g2v3`, `g32v3`, `g22v5`) are sized correctly.
- A single malformed object block, such as one carrying a reserved
  qualifier, no longer discards an entire otherwise-valid response.

## [0.3.0] - 2026-07-07

### Changed

- **BREAKING:** Replaced the MESA profile format with mesa-tool's
  PicsProfile schema. `data/template/profile.json`, `load_profile`, and the
  internal `Profile`/`ProfileSection`/`ProfilePoint` model changed shape to a
  direct Python twin of `PicsProfile` (uppercase `Key`/`BO`/`BI`/`AO`/`AI`/`CTR`
  sections, named-struct equipment groups, engineering-unit analog values
  scaled to DNP3 transmission integers on load). Profiles in the old format no
  longer load. See ADR-002 (supersedes ADR-001).

### Added

- Bundled the four mesa-tool PicsProfile conformance profiles
  (`full`, `mandatory_1815`, `mandatory_1547`, `minimal_1547`) under
  `src/dnp3/mesa/data/profiles/`. `full.json` is the CLI default. A
  PicsProfile JSON schema for load-time and CI validation is deferred to a
  follow-up card; the hand-rolled boundary loader in `profile.py` is the
  format's authority for now.
- CTR (counter) and curve support in the mesa outstation: counter points
  register into the existing DNP3 counter database, and curve/schedule AI
  points register at their absolute indices with scaled values. Selector-driven
  curve and schedule editing (multiplexing) is deferred to a follow-up.
- `--profile-name {full,mandatory_1815,mandatory_1547,minimal_1547}` CLI flag
  to select a bundled profile by name; `--profile` still accepts an arbitrary
  path and defaults to the packaged `full.json` when neither is given.

### Fixed

- Packaged-profile resolution now works under non-regular-install packaging
  (zipimport, zipapp) by resolving bundled profiles through
  `importlib.resources.as_file` instead of assuming a real filesystem path;
  the startup summary now prints a stable package-relative identity.
  `--profile` and `--profile-name` are now a real argparse mutually
  exclusive group.
- Counter event timestamps default to change time instead of poll time.
- Duplicate AI point indices during database construction now raise instead
  of silently deduplicating.
- `engineering_to_transmission` guards against a non-finite
  `engineering_value`.
- g22v5 counter events now carry a 48-bit timestamp.

## [0.2.0] - 2026-06-26

### Added

- MESA IEEE 1815.2 DER outstation module (`dnp3.mesa`): profile-driven
  simulator for meters, DERs, inverters, and batteries loaded from a JSON
  profile file.
- CLI entry point `python -m dnp3.mesa` with flags for profile path, listen
  address/port, DNP3 addresses, and per-entity-type count overrides.
- `create_mesa_outstation` factory function wiring profile, database, AO store,
  command handler, and TCP runner from a single `profile.json`.
- Bundled profile template at `data/template/profile.json`.

### Fixed

- `_SEQ_MASK` restored in transport segment `to_byte` for wire-output integrity.
- FIR/FIN test assertions corrected to match IEEE 1815-2012.
- Inbound multi-fragment reassembly buffer is now bounded to the configured maximum fragment size, preventing an unbounded-memory condition caused by malformed transport input.
- Event response blocks are now chunked to the fragment-size limit, matching the behavior of static responses.

## [0.1.2] - 2026-06-24

### Fixed

- Build release wheel from the tag so PyPI receives a clean PEP 440 version.

## [0.1.1] - 2026-06-24

### Fixed

- DIRECT_OPERATE: echo CROB index at qualifier-derived width; restore
  IIN.PARAMETER_ERROR on FORMAT_ERROR in control response.
- DIRECT_OPERATE echoes command objects back to master.
- WRITE g80v1 clears the restart bit correctly.
- CROB qualifier handling: close silent-failure and DoS gaps; use start/stop
  range qualifiers for static responses; parse CROB count/index by qualifier.
- AO wire-level qualifier, truncation, and count bugs (mirror of CROB fixes).
- Close three review nits: unknown AO variation handling, sentinel value, and
  event-framing 0x28 coverage.

### Changed

- Refactored restart, unsolicited, and event-framing handlers to remove
  duplication.

## [0.1.0] - 2025-12-17

### Added

- Initial release: pure Python DNP3 implementation (IEEE 1815-2012).
- Application, datalink, transport, and transport_io layers.
- Master and outstation roles with object model.
- Full pytest suite with hypothesis property tests; 99% line coverage.
- PyPI publication with hatch build backend.
- GitHub Actions CI across Python 3.11, 3.12, 3.13, 3.14 on Ubuntu and macOS.

[Unreleased]: https://github.com/craigpnnl/dnp3py/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/craigpnnl/dnp3py/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/craigpnnl/dnp3py/compare/v0.3.2...v0.4.0
[0.3.2]: https://github.com/craigpnnl/dnp3py/compare/v0.3.1...v0.3.2
[0.3.1]: https://github.com/craigpnnl/dnp3py/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/craigpnnl/dnp3py/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/craigpnnl/dnp3py/compare/v0.1.2...v0.2.0
[0.1.2]: https://github.com/craigpnnl/dnp3py/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/craigpnnl/dnp3py/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/craigpnnl/dnp3py/releases/tag/v0.1.0
