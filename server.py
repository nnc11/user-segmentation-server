from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import time
import os
import re

app = Flask(__name__)
CORS(app)

# Valid user document fields
VALID_FIELDS = {
    'id', 'level', 'country', 'first_session', 
    'last_session', 'purchase_amount', 'last_purchase_at'
}

STRING_FIELDS = {'id', 'country'}
NUMERIC_FIELDS = {'level', 'first_session', 'last_session', 'purchase_amount', 'last_purchase_at'}

@app.route('/evaluate', methods=['GET'])
def get_test_file():
    """Serve the test.html file"""
    return send_from_directory(os.getcwd(), 'test.html')


def validate_user_document(user):
    """
    Validate user document according to spec:
    - All required fields present
    - No null values
    - Numeric fields are non-negative integers
    - String fields are not empty
    """
    required_fields = ['id', 'level', 'country', 'first_session', 
                      'last_session', 'purchase_amount', 'last_purchase_at']
    
    # Check all required fields present
    for field in required_fields:
        if field not in user:
            raise ValueError(f"Missing required field: {field}")
    
    # Validate each field
    for field, value in user.items():
        # Check for null values
        if value is None:
            raise ValueError(f"Field '{field}' cannot be null")
        
        # Validate string fields
        if field in STRING_FIELDS:
            if not isinstance(value, str):
                raise ValueError(f"Field '{field}' must be a string")
            if value == "":
                raise ValueError(f"Field '{field}' cannot be empty")
        
        # Validate numeric fields
        if field in NUMERIC_FIELDS:
            if not isinstance(value, int):
                raise ValueError(f"Field '{field}' must be an integer")
            if value < 0:
                raise ValueError(f"Field '{field}' must be non-negative")
    
    return True


def extract_fields_from_condition(condition):
    """
    Extract field names from a SQL condition to validate they exist.
    Returns set of field names found.
    """
    # Remove _now() function calls
    temp_condition = re.sub(r'_now\(\)', '', condition)
    
    # Remove string literals (single quotes)
    temp_condition = re.sub(r"'[^']*'", '', temp_condition)
    
    # Remove numbers
    temp_condition = re.sub(r'\b\d+\b', '', temp_condition)
    
    # Remove SQL keywords (case-insensitive)
    sql_keywords = ['and', 'or', 'not', 'in', 'between', 'like']
    for keyword in sql_keywords:
        temp_condition = re.sub(r'\b' + keyword + r'\b', '', temp_condition, flags=re.IGNORECASE)
    
    # Remove operators and parentheses
    temp_condition = re.sub(r'[<>=!()*/+\-,]', ' ', temp_condition)
    
    # Split and filter to get potential field names
    tokens = temp_condition.split()
    fields = set()
    
    for token in tokens:
        token = token.strip()
        if token and token.isidentifier():
            fields.add(token)
    
    return fields


def validate_sql_syntax(condition):
    """
    Basic SQL syntax validation.
    Checks for common syntax errors.
    """
    # Check for balanced parentheses
    if condition.count('(') != condition.count(')'):
        raise ValueError("Unbalanced parentheses in SQL condition")
    
    # Check for invalid operators
    if re.search(r'[<>]=?[<>]|===|!==', condition):
        raise ValueError("Invalid SQL operator syntax")
    
    # Check for empty condition
    if not condition.strip():
        raise ValueError("Empty SQL condition")
    
    return True


def evaluate_condition(user, condition):
    """
    Evaluate a SQL WHERE condition against user data.
    Supports all common ANSI SQL operators.
    """
    now = int(time.time())
    
    # Replace _now() with current timestamp
    condition = re.sub(r'_now\(\)', str(now), condition)
    
    # Validate SQL syntax
    try:
        validate_sql_syntax(condition)
    except ValueError as e:
        raise ValueError(f"Invalid SQL syntax: {str(e)}")
    
    # Extract and validate field names
    fields = extract_fields_from_condition(condition)
    invalid_fields = fields - VALID_FIELDS
    if invalid_fields:
        raise ValueError(f"Unknown fields in segment rule: {', '.join(invalid_fields)}")
    
    # Tokenize and parse the condition
    result = parse_or_expression(user, condition)
    
    return result


def parse_or_expression(user, condition):
    """Parse OR expressions (lowest precedence)"""
    # Split by OR (case-insensitive)
    or_parts = re.split(r'\bor\b', condition, flags=re.IGNORECASE)
    
    if len(or_parts) > 1:
        # Evaluate each part and return True if ANY is true
        return any(parse_and_expression(user, part.strip()) for part in or_parts)
    
    return parse_and_expression(user, condition)


def parse_and_expression(user, condition):
    """Parse AND expressions (medium precedence)"""
    # Split by AND (case-insensitive)
    and_parts = re.split(r'\band\b', condition, flags=re.IGNORECASE)
    
    if len(and_parts) > 1:
        # Evaluate each part and return True only if ALL are true
        return all(parse_not_expression(user, part.strip()) for part in and_parts)
    
    return parse_not_expression(user, condition)


def parse_not_expression(user, condition):
    """Parse NOT expressions (high precedence)"""
    condition = condition.strip()
    
    # Check for NOT at the beginning
    not_match = re.match(r'\bnot\b\s+(.+)', condition, flags=re.IGNORECASE)
    if not_match:
        inner_condition = not_match.group(1).strip()
        return not parse_comparison(user, inner_condition)
    
    return parse_comparison(user, condition)


def parse_comparison(user, condition):
    """Parse comparison expressions and special operators"""
    condition = condition.strip()
    
    # Remove outer parentheses if present
    if condition.startswith('(') and condition.endswith(')'):
        # Check if these are matching outer parentheses
        depth = 0
        for i, char in enumerate(condition):
            if char == '(':
                depth += 1
            elif char == ')':
                depth -= 1
            if depth == 0 and i < len(condition) - 1:
                break
        if i == len(condition) - 1:
            return evaluate_condition(user, condition[1:-1])
    
    # Handle BETWEEN
    between_match = re.match(r'(\w+)\s+between\s+(.+?)\s+and\s+(.+)', condition, flags=re.IGNORECASE)
    if between_match:
        field = between_match.group(1)
        lower = eval_expression(between_match.group(2).strip())
        upper = eval_expression(between_match.group(3).strip())
        return lower <= user[field] <= upper
    
    # Handle IN
    in_match = re.match(r"(\w+)\s+in\s+\((.+?)\)", condition, flags=re.IGNORECASE)
    if in_match:
        field = in_match.group(1)
        values_str = in_match.group(2)
        # Parse the list of values
        values = [v.strip().strip("'\"") for v in values_str.split(',')]
        # Convert numeric strings to integers for numeric fields
        if field in NUMERIC_FIELDS:
            values = [int(v) for v in values]
        return user[field] in values
    
    # Handle LIKE
    like_match = re.match(r"(\w+)\s+like\s+'(.+?)'", condition, flags=re.IGNORECASE)
    if like_match:
        field = like_match.group(1)
        pattern = like_match.group(2)
        # Convert SQL LIKE pattern to regex
        regex_pattern = pattern.replace('%', '.*').replace('_', '.')
        return re.match('^' + regex_pattern + '$', str(user[field])) is not None
    
    # Handle standard comparison operators: <=, >=, !=, <>, =, <, >
    # Try to match: field operator value
    comparison_match = re.match(r'(\w+)\s*(<=|>=|!=|<>|=|<|>)\s*(.+)', condition)
    if comparison_match:
        field = comparison_match.group(1)
        operator = comparison_match.group(2)
        value_expr = comparison_match.group(3).strip()
        
        # Get the user's field value
        user_value = user[field]
        
        # Parse the right-hand side value
        if value_expr.startswith("'") or value_expr.startswith('"'):
            # String value
            compare_value = value_expr.strip("'\"")
        else:
            # Numeric expression
            compare_value = eval_expression(value_expr)
        
        # Perform comparison
        if operator == '=':
            return user_value == compare_value
        elif operator in ('!=', '<>'):
            return user_value != compare_value
        elif operator == '<':
            return user_value < compare_value
        elif operator == '>':
            return user_value > compare_value
        elif operator == '<=':
            return user_value <= compare_value
        elif operator == '>=':
            return user_value >= compare_value
    
    # If we get here, the condition format is not recognized
    raise ValueError(f"Invalid condition format: {condition}")


def eval_expression(expression):
    """
    Safely evaluate arithmetic expressions.
    Only allows numbers and basic math operators.
    """
    expression = str(expression).strip()
    
    # Remove all whitespace
    expression = expression.replace(' ', '')
    
    # Validate expression only contains safe characters
    if not re.match(r'^[0-9+\-*/() ]+$', expression):
        raise ValueError(f"Invalid expression: {expression}")
    
    # Evaluate the expression
    try:
        return int(eval(expression))
    except Exception as e:
        raise ValueError(f"Error evaluating expression '{expression}': {str(e)}")


@app.route('/evaluate', methods=['POST'])
def evaluate_segments():
    """Main endpoint for evaluating user segments"""
    try:
        # Get JSON data
        data = request.get_json()
        
        if data is None:
            return jsonify({"error": "Invalid JSON"}), 400
        
        # Check required top-level fields
        if 'user' not in data:
            return jsonify({"error": "Missing 'user' field"}), 400
        
        if 'segments' not in data:
            return jsonify({"error": "Missing 'segments' field"}), 400
        
        user = data['user']
        segments = data['segments']
        
        # Validate user document
        try:
            validate_user_document(user)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        
        # Evaluate each segment
        results = {}
        for segment_name, rule in segments.items():
            try:
                results[segment_name] = evaluate_condition(user, rule)
            except ValueError as e:
                # Invalid SQL or unknown field
                return jsonify({"error": f"Error in segment '{segment_name}': {str(e)}"}), 400
            except KeyError as e:
                # Field not found in user data (shouldn't happen after validation)
                return jsonify({"error": f"Field {str(e)} not found in user document"}), 400
            except Exception as e:
                # Any other error
                return jsonify({"error": f"Error evaluating segment '{segment_name}': {str(e)}"}), 400
        
        return jsonify({"results": results})
    
    except Exception as e:
        return jsonify({"error": f"Server error: {str(e)}"}), 400


if __name__ == '__main__':
    # Read PORT from environment variable, default to 3000
    port = int(os.environ.get('PORT', 3000))
    app.run(host='0.0.0.0', debug=True, port=port) 