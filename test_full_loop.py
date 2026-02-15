"""
Full Loop Test: XML → Excel → XML → Compare
Tests the complete workflow with Tuning2.xml
"""

import sys
import os
from ncm_core import XMLToExcelConverter, ExcelToXMLConverter, XMLComparator

def test_full_loop():
    """Test the complete conversion and comparison loop"""

    # File paths
    original_xml = r"C:\Users\malek.mohammad\OneDrive - Zain Jordan\Desktop\Nokia XMLS\Tuning2.xml"
    excel_output = r"C:\Users\malek.mohammad\Project\Web_V2\test_output\Tuning2.xlsx"
    regenerated_xml = r"C:\Users\malek.mohammad\Project\Web_V2\test_output\Tuning2_regenerated.xml"
    comparison_report = r"C:\Users\malek.mohammad\Project\Web_V2\test_output\comparison_report.xlsx"

    # Create output directory
    os.makedirs(r"C:\Users\malek.mohammad\Project\Web_V2\test_output", exist_ok=True)

    print("="*80)
    print("FULL LOOP TEST: XML -> Excel -> XML -> Compare")
    print("="*80)
    print()

    # Step 1: XML to Excel
    print("[STEP 1] Converting XML to Excel...")
    print(f"  Input:  {original_xml}")
    print(f"  Output: {excel_output}")

    try:
        converter1 = XMLToExcelConverter(original_xml, excel_output)
        success, message = converter1.convert()

        if success:
            print(f"  ✓ SUCCESS: {message}")
            print(f"  Excel file created: {os.path.exists(excel_output)}")
            print(f"  File size: {os.path.getsize(excel_output)} bytes")
        else:
            print(f"  ✗ FAILED: {message}")
            return False

    except Exception as e:
        print(f"  ✗ ERROR: {str(e)}")
        return False

    print()

    # Step 2: Excel to XML
    print("[STEP 2] Converting Excel back to XML...")
    print(f"  Input:  {excel_output}")
    print(f"  Output: {regenerated_xml}")

    try:
        converter2 = ExcelToXMLConverter(excel_output, regenerated_xml)

        # Discover sheets and set operations
        mo_classes = converter2.discover_sheets()
        print(f"  Found {len(mo_classes)} MO classes: {', '.join(mo_classes[:5])}{'...' if len(mo_classes) > 5 else ''}")

        # Set all operations to "Update" for round-trip
        operations = {mo: 'Update' for mo in mo_classes}
        converter2.set_operations(operations)

        success, message = converter2.convert()

        if success:
            print(f"  ✓ SUCCESS: {message}")
            print(f"  XML file created: {os.path.exists(regenerated_xml)}")
            print(f"  File size: {os.path.getsize(regenerated_xml)} bytes")
        else:
            print(f"  ✗ FAILED: {message}")
            return False

    except Exception as e:
        print(f"  ✗ ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

    print()

    # Step 3: Compare original and regenerated XML
    print("[STEP 3] Comparing original and regenerated XML...")
    print(f"  XML 1: {original_xml}")
    print(f"  XML 2: {regenerated_xml}")
    print(f"  Report: {comparison_report}")

    try:
        comparator = XMLComparator(original_xml, regenerated_xml, comparison_report)

        def progress_callback(percent, status):
            print(f"  Progress: {percent}% - {status}")

        success, diff_count = comparator.compare(progress_callback=progress_callback)

        if success:
            print(f"  ✓ SUCCESS")
            print(f"  Differences found: {diff_count}")
            print(f"  Comparison report created: {os.path.exists(comparison_report)}")

            if hasattr(comparator, 'added_count'):
                print(f"    - Added: {comparator.added_count}")
            if hasattr(comparator, 'removed_count'):
                print(f"    - Removed: {comparator.removed_count}")
            if hasattr(comparator, 'modified_count'):
                print(f"    - Modified: {comparator.modified_count}")
            if hasattr(comparator, 'same_count'):
                print(f"    - Same: {comparator.same_count}")
        else:
            print(f"  ✗ FAILED: Differences found: {diff_count}")

    except Exception as e:
        print(f"  ✗ ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

    print()
    print("="*80)
    print("TEST COMPLETE")
    print("="*80)

    return True

if __name__ == '__main__':
    success = test_full_loop()
    sys.exit(0 if success else 1)
