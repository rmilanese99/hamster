[![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)](https://www.python.org/downloads/release/python-3110/)

<h3 align="center">Hamster: A Large-Scale Study and Characterization of Developer-Written Tests</h3>

<p align="center">
  <img src="doc/hamster.jpg" width="250" height="250">
</p>

<p align="center">
  <em>A comprehensive analysis framework for understanding developer-written Java tests at scale</em>
</p>

---

## Overview

Automated test generation (ATG) has been investigated for decades, producing techniques based on symbolic analysis, search-based, random/adaptive-random, learning-based, and large-language-model-based approaches. Despite this large body of research, there remains a significant gap in understanding the characteristics of developer-written tests.

**Hamster** bridges this gap through an extensive empirical study of developer-written tests for Java applications, covering **1.7 million test cases**. This study is the first of its kind to examine aspects of developer-written tests that are mostly neglected in existing literature:

- **Test Scope** — Unit, Integration, UI, and API test classification
- **Test Fixtures** — Setup and teardown complexity analysis
- **Assertion Patterns** — Types, sequences, and assertion complexity
- **Input Types** — Structured data inputs (JSON, XML, YAML, SQL, etc.)
- **Mocking Usage** — Framework detection and mock complexity

Our results highlight that a vast majority of developer-written tests exhibit characteristics and complexity beyond the capabilities of current ATG tools, identifying promising research directions for bridging this gap.

---

## Key Features

### Test Scope Classification

Hamster identifies the **focal class** (class under test) for each test method and classifies tests into categories:

| Test Type | Description |
|-----------|-------------|
| **Unit/Module** | Tests with a single focal class |
| **Integration** | Tests involving multiple focal classes |
| **UI** | Tests using UI frameworks (Selenium, Selenide, Playwright) |
| **API** | Tests using API testing frameworks (REST Assured, MockMvc) |
| **Library** | Tests that only exercise library code |

### Comprehensive Test Analysis

For each test method, Hamster extracts:

- **Complexity Metrics** — NCLOC, cyclomatic complexity (with/without helpers)
- **Fixture Analysis** — Setup/teardown methods, execution order, resource cleanup
- **Assertion Details** — Type classification, call sequences, wrapped vs. direct assertions
- **Mocking Information** — Framework detection, mock counts, mocked resources
- **Input Analysis** — Structured input detection (JSON, XML, YAML, CSV, SQL, HTML, etc.)
- **Helper Method Tracking** — Reachability analysis across test helpers

### Supported Testing Frameworks

<table>
<tr>
<td>

**Core Frameworks**
- JUnit 3/4/5
- TestNG
- Spock

</td>
<td>

**Assertion Libraries**
- Hamcrest
- AssertJ
- Google Truth

</td>
<td>

**Mocking Frameworks**
- Mockito
- EasyMock
- PowerMock
- JMockit

</td>
</tr>
<tr>
<td>

**BDD Frameworks**
- Cucumber
- JBehave
- Serenity
- Gauge

</td>
<td>

**API Testing**
- REST Assured
- MockMvc
- WebTestClient
- Spring Test

</td>
<td>

**UI Testing**
- Selenium
- Selenide
- Playwright
- Espresso
- Appium

</td>
</tr>
</table>

### Assertion Type Classification

Hamster classifies assertions into semantic categories:

| Category | Examples |
|----------|----------|
| **Truthiness** | `assertTrue`, `assertFalse`, `isTrue` |
| **Equality** | `assertEquals`, `isEqualTo`, `equalTo` |
| **Identity** | `assertSame`, `isInstanceOf`, `sameInstance` |
| **Nullness** | `assertNull`, `isNotNull`, `nullValue` |
| **Numeric Tolerance** | `assertEquals` with delta, `isCloseTo` |
| **Throwable** | `assertThrows`, `assertThatThrownBy` |
| **Collection** | `assertArrayEquals`, `contains`, `hasSize` |
| **String** | `startsWith`, `containsString`, `matches` |
| **Comparison** | `isGreaterThan`, `lessThan`, `isBetween` |

---

## Project Structure

```
src/hamster/code_analysis/
├── focal_class_method/      # Test scope and focal class identification
│   └── focal_class_method.py
├── test_statistics/         # Comprehensive test analysis
│   ├── test_class_analysis_info.py
│   ├── test_method_analysis_info.py
│   ├── call_and_assertion_sequence_details_info.py
│   ├── input_analysis.py
│   ├── setup_analysis_info.py
│   └── teardown_analysis_info.py
├── model/                   # Data models and enums
│   └── models.py
├── common/                  # Shared analysis utilities
│   ├── exceptions.py        # Custom exceptions for analysis errors
│   └── java_analyzer.py     # CommonAnalysis and Reachability classes
└── utils/                   # Constants and configuration
    └── constants.py
```

---

## Usage

### Prerequisites

- Python 3.11+
- [CLDK](https://github.com/IBM/codenet-minerva-code-analyzer) for Java code analysis

### Pipeline

1. **Download GitHub repositories**
   ```bash
   # Clone target Java repositories for analysis
   ```

2. **Run CLDK and generate code analysis**
   ```bash
   # Generate Java analysis using CLDK
   ```

3. **Generate Hamster model**
   ```bash
   # Process CLDK output through Hamster analysis
   ```

4. **Generate dataset statistics**
   ```bash
   # Aggregate and export analysis results
   ```

---

## Output Model

Hamster produces structured analysis output including:

```python
ProjectAnalysis
├── dataset_name
├── application_class_count
├── application_method_count
├── test_class_analyses[]
│   ├── qualified_class_name
│   ├── testing_frameworks[]
│   ├── setup_analyses[]
│   ├── teardown_analyses[]
│   └── test_method_analyses[]
│       ├── test_type (unit/integration/ui/api/library)
│       ├── focal_classes[]
│       ├── ncloc / cyclomatic_complexity
│       ├── call_assertion_sequences[]
│       ├── test_inputs[]
│       └── mocking details
```

---

## Citation

If you use Hamster in your research, please cite our work:

```bibtex
@misc{pan2025hamsterlargescalestudycharacterization,
      title={Hamster: A Large-Scale Study and Characterization of Developer-Written Tests},
      author={Rangeet Pan and Tyler Stennett and Raju Pavuluri and Nate Levin and Alessandro Orso and Saurabh Sinha},
      year={2025},
      eprint={2509.26204},
      archivePrefix={arXiv},
      primaryClass={cs.SE},
      url={https://arxiv.org/abs/2509.26204},
}
```

---

## License

[TBD]

---

## FAQs

**Q: What Java versions are supported?**
A: Hamster uses CLDK for analysis, which supports Java 8+.

**Q: Can I analyze my own projects?**
A: Yes! Follow the usage pipeline to analyze any Java project with test suites.

**Q: How does focal class detection work?**
A: Hamster analyzes variable declarations, call sites, and constructor invocations to identify which application classes are exercised by each test, excluding producer-consumer relationships.