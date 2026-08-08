# PRIVUP - VER 0.0.1 - OPEN SOURCE ARCH

PrivUp stands for **Privacy Up**.

The main motive behind PrivUp is to help users understand **what they are actually agreeing to when giving access to a service, application, or company**.

# PrivUp Open-Source Architecture
  
                         User gives a link or name of the service/app/company
                                              |                           
                                              V                           
                      PrivUp  Scrap their Privacy Polices or term of condition             - > How to scrap not finalized yet and for finding sites(current plan): 
                                              |                                                         1. Make a dataset for service and their privacy polices pages URL (will be limited)
                                              |                                                         2. Can use basic pattern recognition (not reliable but)
                                              |                                                         3. Use a model (Slow and costly)
                                              |                                  
                                              V                                 
                       We will have some tags, or it may be optional so the system can 
                       search specific info from the pages or without tag it will 
                                   get full info from pages.
                                              |
                                              V
                        Use summarizing models to get summary of the pages this arch
                        will allow to use any time of model  so user can add there 
                        custom models. or they will have the default one.
                                (i  might build one or use one )
                                              |
                                              V
                        Return the summary   with minimal text and a score whether  
                         this site or service or app should be used or not or its 
                           real or fake. We had to create some benchmarks too.

                        
                      
# Think Like

```text
                         CORE
                          |
             +------------+------------+
             |            |            |
             V            V            V
          Scraper      Analyzer      Models
             |            |
             V            V
         Document      Findings
                          |
                 +--------+--------+
                 |                 |
                 V                 V
            Summarizer          Scorer
                 |                 |
                 +--------+--------+
                          |
                          V
                     Final Result
```

# Thinking of File Structure

```text
PrivUp/
│
├── core/
│   ├── scraper/
│   │   ├── __init__.py
│   │   ├── fetcher.py
│   │   ├── extractor.py
│   │   └── resolver.py
│   │
│   ├── summarizer/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   └── ...
│   │
│   ├── analyzer/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   └── ...
│   │
│   ├── scorer/
│   │   ├── __init__.py
│   │   └── scorer.py
│   │
│   ├── tags/
│   │   ├── __init__.py
│   │   └── registry.py
│   │
│   └── models/
│       ├── __init__.py
│       └── schemas.py
│
├── tests/
│
├── examples/
│
├── docs/
│
├── README.md
├── pyproject.toml
└── LICENSE
```

# Future

The core would then find and analyze only the camera-related information from the policy and return the relevant result.

```text
User
 |
 | Camera Permission
 V
PrivUp
 |
 | camera tag
 V
Privacy Policy
 |
 V
Camera-related information
 |
 V
Summary + Score + Relevant Information
```


                        
